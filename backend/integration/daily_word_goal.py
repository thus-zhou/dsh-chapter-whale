"""Date-bound goals use platform-confirmed word counts, not generated targets."""
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from . import bridge, writer_runner as writer
from fanqie_auto_publish.publication_safety import valid_receipt


def progress(job, day):
    target = job.get('daily_word_goals', {}).get(day, 0)
    result = {'date': day, 'target': target, 'confirmed_words': 0,
              'counted_chapters': [], 'unknown_word_counts': []}
    if not target:
        return result
    snapshot = bridge.read_json(bridge.COMBINED_ROOT / 'integration_data' /
                                'real_acceptance' / 'all-published-platform.json', {})
    snapshots = {}
    if snapshot.get('book') == job['book'] and snapshot.get('account') == job['account']:
        for item in snapshot.get('chapters', []):
            if isinstance(item, dict) and item.get('body_matches') is True and item.get('status') == '已发布':
                snapshots[str(Path(item.get('archive_path', '')).resolve())] = item
    folder = bridge.UPLOADED_ROOT / bridge.safe_dir_name(job['book'])
    groups={}
    for source in folder.rglob('*.txt'):
        if folder.resolve() not in source.resolve().parents:
            raise ValueError('字数统计归档路径越界，未累计')
        receipt = bridge.read_json(source.with_suffix(source.suffix + '.publish.json'), {})
        number = receipt.get('chapter_id')
        if type(number) is not int or not valid_receipt(source, job['book'], number, job['account']):
            continue
        try:
            verified = datetime.fromisoformat(receipt['verified_at'])
            if verified.tzinfo is None:continue
        except (ValueError, KeyError, TypeError):
            continue
        digest=(receipt.get('file_sha256'),receipt.get('body_sha256'))
        group=groups.setdefault(number,{'digest':digest,'first_verified':verified,'words':set(),'publication_dates':set()})
        if group['digest']!=digest:raise ValueError('同章归档存在不同正文证据，字数统计停止')
        group['first_verified']=min(group['first_verified'],verified)
        if receipt.get('platform_published_at') is not None:
            try:
                published=datetime.fromisoformat(receipt['platform_published_at'])
                if published.tzinfo is None or published>verified+timedelta(minutes=1):raise ValueError()
            except (ValueError,TypeError):
                raise ValueError('平台发布时间证据无效，字数统计停止') from None
            group['publication_dates'].add(published.astimezone(ZoneInfo(job['timezone'])).date().isoformat())
        words = receipt.get('platform_words')
        if type(words) is not int or words <= 0:
            saved = snapshots.get(str(source.resolve()), {})
            try:
                fresh = datetime.fromisoformat(snapshot['checked_at']) >= verified
            except (ValueError, TypeError, KeyError):
                fresh = False
            words = saved.get('words') if fresh and saved.get('chapter_id')==number else None
        if type(words) is int and words>0:group['words'].add(words)
    for number,group in sorted(groups.items()):
        dates=group['publication_dates']
        if len(dates)>1:raise ValueError('同章平台发布时间证据冲突，字数统计停止')
        published_day=next(iter(dates)) if dates else group['first_verified'].astimezone(ZoneInfo(job['timezone'])).date().isoformat()
        if published_day!=day:continue
        if len(group['words'])>1:raise ValueError('同章平台字数证据冲突，统计停止')
        if not group['words']:
            result['unknown_word_counts'].append(number);continue
        result['confirmed_words'] += next(iter(group['words']))
        result['counted_chapters'].append(number)
    return result


def reserve(job, day):
    value=progress(job,day)
    if not value['target'] or value['confirmed_words']>=value['target']:return None
    if value['unknown_word_counts']:
        raise ValueError('已发布章节缺少平台字数证据，需核对后继续补量，禁止将未知字数当作0')
    number=writer.next_chapter_id(Path(job['project']))
    return {'run_date':day,'slot':f'{day}@09:00+word-goal-{number}',
            'target_ids':[number],'status':'continuing','word_count':job['word_count'],
            'max_revisions':job['max_revisions'],'word_goal_supplement':True}


def supplement(job, cycle, record):
    """Close the old immutable cycle before reserving ONE additional chapter."""
    from . import scheduler as scheduler
    # Read the latest goal: changing it must not invalidate the active chapter.
    latest = scheduler.load_scheduler()['jobs'].get(record['job_id'], job)
    day = scheduler._job_today(latest)
    if day != cycle['run_date']:
        return None
    value = progress(latest, day)
    if not value['target']:
        return None
    record['daily_word_goal'] = value
    return reserve(latest,day)
