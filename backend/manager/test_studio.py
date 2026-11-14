"""Offline acceptance for learning, A–E roles, planning and durable batches."""
import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from fastapi.testclient import TestClient
from manager import app as module
from integration import studio, writer_runner as writer, model_roles as roles, bridge, memory_library

PASS={"success":True,"review_decision":"pass","needs_revision":False}


class StudioTests(unittest.TestCase):
    def test_saved_chapter_polish_keeps_classified_error_and_preserves_source(self):
        from integration.failure_info import PolishIncomplete,details
        source=self.project/'正文/第1章-原稿.md';source.write_text('保存的原稿。',encoding='utf-8')
        executor=Mock();executor.execute_polish=AsyncMock(return_value={
            'success':False,'error':'输出截断','failure_kind':'model_output','retryable':True})
        with patch.object(writer,'_load_webnovel_services',return_value=(Mock(return_value=executor),lambda:Mock())):
            with self.assertRaises(PolishIncomplete) as caught:
                studio.polish_existing(self.project,1,min_words=5001)
        self.assertEqual(details(caught.exception)['failure_kind'],'model_output')
        self.assertTrue(details(caught.exception)['retryable'])
        self.assertEqual(source.read_text(encoding='utf-8'),'保存的原稿。')

    def test_new_manual_batch_cannot_replace_a_frozen_serial_cycle(self):
        from integration import scheduler
        job={'project':str(self.project),'delivery_mode':'serial','cycle':{'status':'failed','target_ids':[1,2]}}
        with patch.object(scheduler,'load_scheduler',return_value={'jobs':{'daily':job}}), \
             patch.object(writer,'_generate_chapter_locked',AsyncMock()) as generate:
            with self.assertRaisesRegex(ValueError,'原日更任务'):
                studio.batch(self.project,1,5000,2,'a'*32)
        generate.assert_not_awaited()
        self.assertFalse(studio.project_file(self.project,'batches','a'*32).exists())

    def test_resumed_first_D_review_receives_saved_editorial_history(self):
        self.config['polish_mode']='none';writer.atomic_json(self.ai_path,self.config)
        (self.project/'大纲'/'卷一.md').write_text('## 第1章 来信\n发现线索。',encoding='utf-8')
        contexts=[]
        class Executor:
            def __init__(self,**kwargs):pass
            async def execute_write_stream(self,*args,**kwargs):
                yield json.dumps({'type':'content','chunk':'保留的原稿正文。'})
                yield json.dumps({'type':'done','success':True})
            async def execute_review(self,chapter_id,content):
                contexts.append(self.editorial_review_context)
                return PASS if len(contexts)>1 else {'success':True,'review_decision':'needs_revision',
                    'needs_revision':True,'raw_review':'持久化历史标记：核对原文铜牌凿痕。'}
        with patch.object(writer,'_load_webnovel_services',return_value=(Executor,lambda:Mock())):
            with self.assertRaises(RuntimeError):
                asyncio.run(writer._generate_and_review(self.project,1,3000,0))
            result=asyncio.run(writer._generate_and_review(self.project,1,3000,0))
        self.assertIn('持久化历史标记',contexts[1])
        self.assertEqual(result['review']['review_decision'],'pass')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=module.ROOT);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.project=self.root/"project"
        for folder in ("正文","大纲",".webnovel"):(self.project/folder).mkdir(parents=True)
        writer.atomic_json(self.project/".webnovel"/"state.json",{"title":"离线测试","current_chapter":0})
        self.config={"base_url":"https://fixture.invalid/v1","model":"fallback-model","api_key":"NOT-A-REAL-KEY","multi_model":True,
            "roles":{r:{"model":r+"-model"} for r in roles.ROLES},"polish_mode":"key","review_policy":"strict"}
        self.enterContext(patch.object(memory_library,"sync_chapter",AsyncMock(return_value={"status":"synced"})))
        self.ai_path=self.root/"ai.json";writer.atomic_json(self.ai_path,self.config)
        self.enterContext(patch.dict("os.environ",{"NOVEL_HELPER_AI_CONFIG":str(self.ai_path)}))
        self.enterContext(patch.object(module,"DATA",self.root));self.enterContext(patch.object(module,"AI_PATH",self.ai_path))
        self.application=module.create_app(self.root/"db.sqlite",start_dispatcher=False)
        self.client=TestClient(self.application);self.addCleanup(self.client.close)
        self.identity=self.application.state.store.register(self.project);self.headers={"X-Novel-Helper":"1"}
        self.service=studio.brief_service()
        self.executor=Mock();self.executor._extract_chapter_entities=AsyncMock(return_value={"extraction":{}})
        self.executor._apply_extraction_results=AsyncMock(return_value={"updated":True})
        self.executor.sync_post_save_artifacts=AsyncMock(return_value={"rag_indexed":True})

    def learn_result(self):return {"guide":"短句推进，对话有潜台词；先埋具体物件，再在转折回收。","brief":{"style":"克制且有画面感","pacing":"循序铺垫，关键节点反转"}}

    def planner_result(self,start=1,count=2):
        return {"master_outline":"一个普通人的成长故事","volumes":"第一卷解决身份谜团","character_arcs":"从逃避到承担责任","foreshadowing":"第1章来信，第2章解释寄信人",
            "chapters":[{"id":i,"title":f"标题{i}","outline":f"第{i}次调查；推进线索，留下钩子。","key_scene":i==start} for i in range(start,start+count)]}

    def test_upload_encoding_sanitized_name_and_multipart_endpoint(self):
        item=studio.upload(self.project,"../../示范.txt","这是中文示范。".encode("gb18030"))
        self.assertEqual(item["name"],"示范.txt");self.assertEqual(item["encoding"],"gb18030")
        response=self.client.post(f"/api/projects/{self.identity}/samples",files={"file":("示范2.txt","全文。".encode("utf-16"),"text/plain")},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(self.client.get(f"/api/projects/{self.identity}/samples").json()),2)

    def test_upload_rejects_nontext_oversize_empty_and_invalid_id(self):
        for name,raw in (("x.pdf",b"hello"),("x.txt",b"\0binary"),("x.txt",b" "),("x.txt",b"x"*(studio.MAX_UPLOAD+1))):
            with self.assertRaises(ValueError):studio.upload(self.project,name,raw)
        with self.assertRaises(ValueError):studio.project_file(self.project,"samples","../../key")

    def test_learning_auto_fills_and_persists_guidance_without_copying_source(self):
        sample=studio.upload(self.project,"示范.txt","山雨落在窗台，主人公没有说话。".encode())
        mocked=AsyncMock(side_effect=[{"analysis":"短句与留白"},self.learn_result()])
        with patch.object(roles,"json_call",mocked):result=studio.learn(self.project,sample["id"],0)
        self.assertEqual(result["status"],"learned")
        self.assertEqual(self.service.read_document(self.project)["brief"]["style"],"克制且有画面感")
        self.assertIn("短句推进",self.service.load_guidance(self.project))
        self.assertEqual(studio.sample_list(self.project)[0]["analyzed_segments"],1)
        self.assertEqual(list((self.project/"正文").iterdir()),[])
        self.assertNotIn("主人公没有说话",self.service.load_guidance(self.project))
        self.assertTrue(list((self.project/".webnovel"/"creative-backups").glob("*.json")))
        with patch.object(roles,"json_call",side_effect=AssertionError("Completed learning must be idempotent")):
            self.assertEqual(studio.learn(self.project,sample["id"],0)["status"],"learned")

    def test_learning_failure_preserves_brief_and_resumes_map_checkpoint(self):
        text="测试片段。"*6000;sample=studio.upload(self.project,"示范.txt",text.encode())
        with patch.object(roles,"json_call",AsyncMock(side_effect=[{"analysis":"第一段记录"},ValueError("failure")])):
            with self.assertRaises(ValueError):studio.learn(self.project,sample["id"],0,True)
        self.assertEqual(self.service.read_document(self.project)["revision"],0)
        self.assertEqual(studio.sample_list(self.project)[0]["status"],"failed")
        remaining=len(studio.segments(text,True))-1
        mock=AsyncMock(side_effect=[{"analysis":"后续段"}]*remaining+[self.learn_result()])
        with patch.object(roles,"json_call",mock):result=studio.learn(self.project,sample["id"],0,True)
        self.assertEqual(mock.await_count,remaining+1);self.assertEqual(result["status"],"learned")

    def test_full_analysis_reduces_all_segments_not_just_first_notes(self):
        text="全段测试。"*28000;sample=studio.upload(self.project,"full.txt",text.encode())
        count=len(studio.segments(text,True));calls=[]
        async def respond(role,prompt,config=None,**kwargs):
            calls.append(prompt)
            if prompt.startswith("分析这段"):return {"analysis":f"分段记号{sum(p.startswith('分析这段') for p in calls)}"}
            if prompt.startswith("合并这些"):return {"analysis":"汇总："+prompt.split("\n",1)[1]}
            return self.learn_result()
        with patch.object(roles,"json_call",side_effect=respond):result=studio.learn(self.project,sample["id"],0,True)
        self.assertIn(f"分段记号{count}",calls[-1]);self.assertEqual(result["creative"]["learning"]["segments"],count)

    def test_learning_commit_recovery_after_status_write_failure(self):
        sample=studio.upload(self.project,"x.txt","学习原文。".encode());original=writer.atomic_json
        def save(path,value):
            if Path(path)==studio.project_file(self.project,"samples",sample["id"]) and value.get("status")=="learned":raise OSError("disk status failure")
            return original(path,value)
        with patch.object(roles,"json_call",AsyncMock(side_effect=[{"analysis":"技法"},self.learn_result()])),patch.object(writer,"atomic_json",side_effect=save):
            with self.assertRaises(OSError):studio.learn(self.project,sample["id"],0)
        with patch.object(roles,"json_call",side_effect=AssertionError("Do not re-run AI after commit")):
            result=studio.learn(self.project,sample["id"],0)
        self.assertEqual(result["creative"]["revision"],1)
        self.assertEqual(result["sample"]["status"],"learned")

    def test_stale_brief_learning_and_expansion_are_not_applied(self):
        sample=studio.upload(self.project,"x.txt",b"reference")
        doc=self.service.read_document(self.project);doc["revision"]=2;writer.atomic_json(self.project/".webnovel"/"creative_brief.json",doc)
        with patch.object(roles,"json_call",side_effect=AssertionError("No AI on stale request")):
            with self.assertRaises(ValueError):studio.learn(self.project,sample["id"],0)
            with self.assertRaises(ValueError):studio.expand_brief(self.project,{"style":"简略"},0)

    def test_expand_is_only_preview_and_keeps_user_unsaved_input(self):
        with patch.object(roles,"json_call",AsyncMock(return_value={"brief":{"style":"短句，有动作画面，克制修辞"}})):
            result=studio.expand_brief(self.project,{"style":"短句","characters":"普通大学生"},0)
        self.assertTrue(result["preview"]);self.assertEqual(result["brief"]["characters"],"普通大学生")
        self.assertEqual(self.service.read_document(self.project)["revision"],0)

    def test_planner_saves_exact_chapters_and_global_arcs(self):
        with patch.object(roles,"json_call",AsyncMock(return_value=self.planner_result())):result=studio.plan(self.project,2)
        self.assertEqual(result["chapters"],[1,2]);self.assertIn("标题1",writer._find_outline(self.project,1))
        self.assertEqual(self.client.get(f"/api/projects/{self.identity}/plan").json()["character_arcs"],"从逃避到承担责任")
        self.assertTrue(studio.is_key_scene(self.project,1))
        self.assertFalse(studio.is_key_scene(self.project,2))
        with patch.object(roles,"json_call",side_effect=AssertionError("No overwrite")):
            with self.assertRaises(ValueError):studio.plan(self.project,2)

    def test_planner_truncation_retries_once_before_commit_with_json_mode(self):
        call = AsyncMock(side_effect=[ValueError("模型 A 达到输出 Token 上限（18000），结构化结果被截断"), self.planner_result()])
        with patch.object(roles, "json_call", call):
            result = studio.plan(self.project, 2)
        self.assertEqual(result["chapters"], [1, 2])
        self.assertEqual(call.await_count, 2)
        self.assertEqual(call.await_args_list[0].kwargs["max_tokens"], 18000)
        self.assertEqual(call.await_args_list[1].kwargs["max_tokens"], 32000)
        self.assertEqual(call.await_args_list[0].kwargs["response_format"], "json_object")

    def test_planner_wrong_ids_are_corrected_before_commit(self):
        call=AsyncMock(side_effect=[{**self.planner_result(), 'chapters':[{'id':9}]}, self.planner_result()])
        with patch.object(roles,'json_call',call):result=studio.plan(self.project,2)
        self.assertEqual(result['chapters'],[1,2])
        self.assertEqual(call.await_count,2)

    def test_planner_other_errors_do_not_retry_or_save(self):
        call = AsyncMock(side_effect=ValueError("模型 A 未返回有效结果"))
        with patch.object(roles, "json_call", call), self.assertRaises(ValueError):
            studio.plan(self.project, 2)
        self.assertEqual(call.await_count, 1)
        self.assertEqual(list((self.project/"大纲").glob("*.md")), [])

    def test_planner_rejects_wrong_ids_or_missing_fields_without_writing(self):
        for value in ({**self.planner_result(),"chapters":[{"id":9}]},{**self.planner_result(),"character_arcs":""}):
            with patch.object(roles,"json_call",AsyncMock(return_value=value)):
                with self.assertRaises(ValueError):studio.plan(self.project,2)
        self.assertEqual(list((self.project/"大纲").glob("*.md")),[])

    def test_planner_index_recovered_from_committed_markdown(self):
        original=writer.atomic_json
        def fail(path,value):
            if Path(path).name=="story_plan.json":raise OSError("index failure")
            return original(path,value)
        with patch.object(roles,"json_call",AsyncMock(return_value=self.planner_result())),patch.object(writer,"atomic_json",side_effect=fail):
            with self.assertRaises(OSError):studio.plan(self.project,2)
        restored=studio.recover_plan(self.project)
        self.assertEqual(list(restored["chapters"]),["1","2"])
        self.assertTrue(studio.is_key_scene(self.project,1))

    def test_batch_stops_and_recovers_reserved_ids_without_duplicate_writes(self):
        (self.project/"大纲"/"卷一.md").write_text("\n".join(f"## 第{i}章 标题{i}\n具体事件。" for i in range(1,5)),encoding="utf-8")
        calls=[]
        async def generated(project,chapter,words,revisions):
            calls.append(chapter)
            if chapter==2 and calls.count(2)==1:raise ValueError("failed on second")
            return {"content":f"第{chapter}章原创正文。","review":PASS,"revision_rounds":0,"executor":self.executor}
        identity="a"*32
        with patch.object(writer,"_generate_and_review",side_effect=generated):
            with self.assertRaises(ValueError):studio.batch(self.project,3,1000,0,identity)
            with self.assertRaises(ValueError):studio.batch(self.project,3,1000,0,"b"*32)
            result=studio.batch(self.project,1,5000,5,identity)
        self.assertEqual(result["targets"],[1,2,3]);self.assertEqual(calls,[1,2,2,3])
        self.assertEqual(len(list((self.project/"正文").glob("*.md"))),3)

    def test_sample_copy_long_passage_is_rejected(self):
        sample=studio.upload(self.project,"sample.txt",("原文不得复制，"*40).encode())
        doc=self.service.read_document(self.project);doc["learning"]={"sample_id":sample["id"],"guide":"技法"}
        writer.atomic_json(self.project/".webnovel"/"creative_brief.json",doc)
        with self.assertRaises(ValueError):studio.reject_sample_copy(self.project,"原文不得复制，"*30)
        studio.reject_sample_copy(self.project,"这是一段新写的原创正文。")

    def test_manual_polish_preserves_original_on_failed_D_then_commits_backup(self):
        source=self.project/"正文"/"第1章-标题.md";source.write_text("原正文。",encoding="utf-8")
        memory=self.executor;memory.execute_polish=AsyncMock(return_value={"success":True,"content":"新润色正文。"})
        memory.execute_review=AsyncMock(return_value={"success":True,"review_decision":"needs_revision","needs_revision":True})
        with patch.object(writer,"_load_webnovel_services",return_value=(lambda *a:memory,lambda:Mock())),patch.object(bridge,"load_manifest",return_value={"books":{}}):
            with self.assertRaises(ValueError):studio.polish_existing(self.project,1)
            self.assertEqual(source.read_text(encoding="utf-8"),"原正文。")
            memory.execute_review.return_value=PASS
            result=studio.polish_existing(self.project,1)
        self.assertEqual(result["status"],"polished");self.assertIn(1,writer.reviewed_chapters(self.project))
        self.assertEqual(source.read_text(encoding="utf-8"),"新润色正文。")
        backups=list((self.project/".webnovel"/"originals").glob("*.md"))
        self.assertEqual(backups[0].read_text(encoding="utf-8"),"原正文。")

    def test_role_settings_credentials_never_echo_and_keys_bind_to_provider(self):
        values={r:{"model":r+"-model"} for r in roles.ROLES}
        values["C"].update(base_url="https://second.invalid/v1",api_key="PRIVATE-C-KEY")
        response=self.client.put("/api/ai/roles",json={"multi_model":True,"roles":values,"review_policy":"e_decides"},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text);self.assertNotIn("PRIVATE-C-KEY",response.text)
        self.assertEqual(roles.connection("C",roles.load_config())["api_key"],"PRIVATE-C-KEY")
        values["C"]["base_url"]="https://third.invalid/v1";values["C"]["api_key"]=""
        self.assertEqual(self.client.put("/api/ai/roles",json={"multi_model":True,"roles":values},headers=self.headers).status_code,400)
        self.assertEqual(roles.connection("C",roles.load_config())["base_url"],"https://second.invalid/v1")

    def test_role_router_nested_context_and_real_review_hook(self):
        calls=[]
        class Client:
            def __init__(self,role):self.model=role
            async def chat_stream(self,messages,**kwargs):
                calls.append((self.model,messages));yield "结论：无需修改\n原因：符合要求。\n意见：无。"
        router=roles.RoleRouter(self.config,None)
        with patch.object(roles,"service",side_effect=lambda role,*a:Client(role)):
            self.assertEqual(router.model,"B")
            with router.stage("C"):
                self.assertEqual(router.model,"C")
                with router.stage("D"):self.assertEqual(router.model,"D")
                self.assertEqual(router.model,"C")
            from services.skill_executor import SkillExecutor
            executor=SkillExecutor(self.project,router)
            asyncio.run(executor.execute_review(1,"原创正文。"))
        self.assertEqual(calls[-1][0],"D")

    def test_real_polish_hook_uses_C_before_D(self):
        calls=[]
        class Client:
            def __init__(self,role):self.model=role
            async def chat(self,messages,**kwargs):calls.append(self.model);return "修订后的对话清晰、具体，场景在这里结束。"
            async def chat_stream(self,messages,**kwargs):calls.append(self.model);yield "结论：无需修改\n原因：符合设定。\n意见：无。"
        from services.skill_executor import SkillExecutor
        router=roles.RoleRouter(self.config,None);executor=SkillExecutor(self.project,router)
        async def run():
            polished=await executor.execute_polish(1,"原始正文。","优化对话",mode="rewrite")
            self.assertTrue(polished["success"],polished)
            await executor.execute_review(1,polished["content"])
        with patch.object(roles,"service",side_effect=lambda r,*a:Client(r)):
            asyncio.run(run())
        self.assertIn("C",calls);self.assertEqual(calls[-1],"D")

    def test_key_scene_pipeline_calls_B_D_C_D_then_saves_only_final_content(self):
        (self.project/"大纲"/"卷一.md").write_text("## 第1章 来信\n发现线索。",encoding="utf-8")
        writer.atomic_json(self.project/".webnovel"/"story_plan.json",{"chapters":{"1":{"key_scene":True}}})
        stages=[];memory=self.executor
        class Client:
            def __init__(self,role):self.model=role
        class Executor:
            def __init__(self,project_root,ai_service):self.ai_service=ai_service
            async def execute_write_stream(self,chapter,**kwargs):
                stages.append(self.ai_service.model)
                yield json.dumps({"type":"content","chunk":"正文初稿。"})
                review=await self.execute_review(chapter,"正文初稿。")
                yield json.dumps({"type":"review","result":review})
                yield json.dumps({"type":"done","success":True})
            async def execute_review(self,*a,**k):
                with self.ai_service.stage("D"):stages.append(self.ai_service.model)
                return PASS
            async def execute_polish(self,*a,**k):
                with self.ai_service.stage("C"):stages.append(self.ai_service.model)
                return {"success":True,"content":"C 润色后的最终正文。"}
            async def _extract_chapter_entities(self,*a):return await memory._extract_chapter_entities(*a)
            async def _apply_extraction_results(self,*a):return await memory._apply_extraction_results(*a)
            async def sync_post_save_artifacts(self,*a):return await memory.sync_post_save_artifacts(*a)
        with patch.object(writer,"_load_webnovel_services",return_value=(Executor,lambda:Client("base"))),patch.object(roles,"service",side_effect=lambda r,*a:Client(r)):
            result=writer.generate_chapter(self.project)
        self.assertEqual(stages,["B","D","C","D"])
        self.assertEqual(Path(result["destination"]).read_text(encoding="utf-8").strip(),"C 润色后的最终正文。")
        self.assertIn(1,writer.reviewed_chapters(self.project))

    def test_noop_targeted_patch_falls_back_to_C_rewrite_then_D_reviews_changed_body(self):
        self.config.update(review_policy='strict',polish_mode='none');writer.atomic_json(self.ai_path,self.config)
        (self.project/'大纲'/'卷一.md').write_text('## 第1章 来信\n发现线索。',encoding='utf-8')
        modes=[];reviews=[]
        class Executor:
            def __init__(self,**kwargs):pass
            async def execute_write_stream(self,*a,**k):
                yield json.dumps({'type':'content','chunk':'原稿正文。'})
                yield json.dumps({'type':'done','success':True})
            async def execute_review(self,chapter_id,content):
                reviews.append(content)
                return PASS if content!='原稿正文。' else {'success':True,'review_decision':'needs_revision','needs_revision':True,'raw_review':'修正时间矛盾。'}
            async def execute_polish(self,chapter,content,suggestions,mode):
                modes.append(mode)
                return {'success':True,'content':content if mode=='targeted_fix' else '已修订的正文。'}
        with patch.object(writer,'_load_webnovel_services',return_value=(Executor,lambda:Mock())):
            result=asyncio.run(writer._generate_and_review(self.project,1,3000,1))
        self.assertEqual(modes,['targeted_fix','rewrite'])
        self.assertEqual(reviews,['原稿正文。','已修订的正文。'])
        self.assertEqual(result['review']['review_decision'],'pass')

    def test_E_waiver_is_saved_and_exposed_as_authorized_not_review_passed(self):
        self.config.update(review_policy="e_decides",polish_mode="none");writer.atomic_json(self.ai_path,self.config)
        (self.project/"大纲"/"卷一.md").write_text("## 第1章 来信\n发现线索。",encoding="utf-8")
        memory=self.executor
        class Executor:
            def __init__(self,**kwargs):pass
            async def execute_write_stream(self,*a,**k):
                for value in ({"type":"content","chunk":"完整的新正文。"},{"type":"review","result":{"success":True,"review_decision":"needs_revision","needs_revision":True}},{"type":"done","success":True}):yield json.dumps(value)
            async def execute_review(self,*a,**k):
                return {"success":True,"review_decision":"needs_revision","needs_revision":True}
            async def _extract_chapter_entities(self,*a):return await memory._extract_chapter_entities(*a)
            async def _apply_extraction_results(self,*a):return await memory._apply_extraction_results(*a)
            async def sync_post_save_artifacts(self,*a):return await memory.sync_post_save_artifacts(*a)
        with patch.object(writer,"_load_webnovel_services",return_value=(Executor,lambda:Mock())),patch.object(roles,"json_call",AsyncMock(return_value={"action":"continue"})):
            result=writer.generate_chapter(self.project,max_revisions=0)
        self.assertEqual(result["review_decision"],"waived_by_E")
        self.assertFalse(writer.review_passed(result["review"]))
        self.assertIn(1,writer.reviewed_chapters(self.project))
        chapter=self.client.get(f"/api/projects/{self.identity}/chapters").json()["chapters"][0]
        self.assertEqual(chapter["review_status"],"waived_by_E")
        with patch.object(writer,"_generate_and_review",AsyncMock(side_effect=AssertionError("不能重写已保存章节"))):
            recovered=writer.generate_chapter(self.project,chapter_id=1)
        self.assertEqual(recovered["review_decision"],"waived_by_E")
        self.assertFalse(writer.review_passed(recovered["review"]))

    def test_E_can_waive_advisory_review_but_not_fake_pass_or_change_content(self):
        self.config["review_policy"]="e_decides";writer.atomic_json(self.ai_path,self.config)
        advisory={"success":True,"review_decision":"needs_revision","needs_revision":True,"raw_review":"建议优化对话"}
        with patch.object(roles,"json_call",AsyncMock(return_value={"action":"continue","reason":"作者授权，接受此稿"})):
            review=asyncio.run(roles.authorize_draft("正文",advisory,self.config))
        self.assertEqual(review["review_decision"],"waived_by_E");self.assertFalse(writer.review_passed(review))
        self.assertTrue(bridge.review_eligible(review,bridge.body_digest("正文")))
        self.assertFalse(bridge.review_eligible(review,bridge.body_digest("改过的正文")))
        self.config["review_policy"]="strict";writer.atomic_json(self.ai_path,self.config)
        self.assertFalse(bridge.review_eligible(review,bridge.body_digest("正文")))

    def test_connection_probe_leaves_budget_for_reasoning_and_requires_visible_reply(self):
        from manager import worker
        service=Mock(model="reasoning-fixture");service.chat=AsyncMock(return_value="OK")
        with patch.object(writer,"_load_webnovel_services",return_value=(None,lambda:service)):
            self.assertEqual(asyncio.run(worker.test_ai())["status"],"ok")
        self.assertGreaterEqual(service.chat.call_args.kwargs["max_tokens"],512)
        service.chat=AsyncMock(return_value="")
        with patch.object(writer,"_load_webnovel_services",return_value=(None,lambda:service)):
            with self.assertRaisesRegex(RuntimeError,"空内容"):asyncio.run(worker.test_ai())

    def test_E_publish_gate_requires_explicit_publish_action(self):
        plan={"book":"fixture","account":"alias","chapters":[{"chapter_id":1,"review_status":"waived_by_E"}]}
        with patch.object(roles,"json_call",AsyncMock(return_value={"action":"stop"})):
            with self.assertRaises(ValueError):roles.publication_gate(plan)
        with patch.object(roles,"json_call",AsyncMock(return_value={"action":"publish"})):
            self.assertEqual(roles.publication_gate(plan)["mode"],"model_E")

    def test_json_call_reports_truncated_completion_without_leaking_content(self):
        service=Mock(last_response_meta={'finish_reason':'length'})
        service.chat=AsyncMock(return_value='{"secret":"not-for-errors"')
        with patch.object(roles,'service',return_value=service):
            with self.assertRaisesRegex(ValueError,'Token 上限（9000）') as error:
                asyncio.run(roles.json_call('A','fixture',config=self.config,max_tokens=9000))
        self.assertNotIn('not-for-errors',str(error.exception))

    def test_json_call_reports_invalid_json_separately_from_transport(self):
        service=Mock(last_response_meta={'finish_reason':'stop'})
        service.chat=AsyncMock(return_value='not valid JSON')
        with patch.object(roles,'service',return_value=service):
            with self.assertRaisesRegex(ValueError,'不是完整有效的 JSON'):
                asyncio.run(roles.json_call('A','fixture',config=self.config))
        service.chat=AsyncMock(return_value='{"answer":"ok"}')
        with patch.object(roles,'service',return_value=service):
            self.assertEqual(asyncio.run(roles.json_call('A','fixture',config=self.config)),{'answer':'ok'})

    def test_resumed_batch_is_running_before_first_model_request(self):
        identity='a'*32
        path=studio.project_file(self.project,'batches',identity)
        writer.atomic_json(path,{'id':identity,'targets':[1],'word_count':3000,'max_revisions':2,'status':'partial','finished_at':'old'})
        async def observe(*args):
            current=writer.strict_json(path,{})
            self.assertEqual(current['status'],'running')
            self.assertNotIn('finished_at',current)
            raise RuntimeError('fixture failure')
        with patch.object(writer,'_generate_chapter_locked',side_effect=observe):
            with self.assertRaisesRegex(RuntimeError,'fixture failure'):
                studio.batch(self.project,1,3000,2,identity)
        self.assertEqual(writer.strict_json(path,{})['status'],'partial')

    def test_failed_polish_retains_B_checkpoint_and_resume_does_not_redraft(self):
        events=[{'type':'content','chunk':'完整初稿。'},{'type':'review','result':PASS},{'type':'done','success':True,'content':'完整初稿。'}]
        async def event_stream(*args,**kwargs):
            for item in events:yield json.dumps(item,ensure_ascii=False)
        executor=Mock()
        executor.execute_write_stream.side_effect=event_stream
        executor.execute_polish=AsyncMock(side_effect=[{'success':False},{'success':True,'content':'完整润色稿。'}])
        executor.execute_review=AsyncMock(return_value=PASS)
        self.config['polish_mode']='all';writer.atomic_json(self.ai_path,self.config)
        with patch.object(writer,'_load_webnovel_services',return_value=(Mock(return_value=executor),lambda:Mock())):
            with self.assertRaisesRegex(RuntimeError,'中间稿已保留'):
                asyncio.run(writer._generate_and_review(self.project,1,3000,2))
            result=asyncio.run(writer._generate_and_review(self.project,1,3000,2))
        self.assertEqual(result['content'],'完整润色稿。')
        self.assertEqual(executor.execute_write_stream.call_count,1)
        self.assertEqual(list((self.project/'正文').glob('*.md')),[])

    def test_glm_forced_thinking_routing_keeps_model_and_controls_effort(self):
        self.config['roles']['C']['model']='GLM-5.3'
        self.config['roles']['D']['model']='GLM-5.3-Flash'
        self.assertEqual(roles.service('C',self.config).reasoning_effort,'low')
        self.assertEqual(roles.service('D',self.config).reasoning_effort,'high')
        self.assertEqual(roles.service('B',self.config).reasoning_effort,None)
        self.config['roles']['B']['model']='DeepSeek-V4.1-Flash'
        self.assertEqual(roles.service('B',self.config).reasoning_effort,'low')

    def test_E_stop_reports_reason_without_granting_qualification(self):
        self.config['review_policy']='e_decides'
        with patch.object(roles,'json_call',AsyncMock(return_value={'action':'stop','reason':'视频镜头中消失的人写反了'})):
            with self.assertRaisesRegex(ValueError,'视频镜头中消失的人写反了'):
                asyncio.run(roles.authorize_draft('正文',{'review_decision':'needs_revision'},self.config))

    def test_E_can_request_revision_without_waiving_D_or_approving_current_body(self):
        self.config['review_policy']='e_decides'
        advisory={'success':True,'review_decision':'needs_revision','needs_revision':True,'raw_review':'修正时间线'}
        with patch.object(roles,'json_call',AsyncMock(return_value={'action':'revise','reason':'先改再审'})):
            result=asyncio.run(roles.authorize_draft('正文',advisory,self.config))
            self.assertFalse(bridge.review_eligible(result,bridge.body_digest('正文')))
            self.assertEqual(result['executor_decision']['action'],'revise')
            with self.assertRaisesRegex(ValueError,'没有有效的 D'):
                asyncio.run(roles.authorize_draft('正文',{'success':False,'review_decision':'unknown'},self.config))


if __name__=="__main__":unittest.main()
