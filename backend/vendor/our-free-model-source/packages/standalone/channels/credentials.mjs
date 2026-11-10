import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { spawnSync } from 'node:child_process'

/** 独立应用凭据仓库。同步原子写入，失败冒泡；从不读取 DSH 文件。 */
export function createCredentials(dataDir) {
  const file = path.join(dataDir, 'channel-credentials.json')
  let values = {}
  if (fs.existsSync(file)) {
    const loaded = JSON.parse(fs.readFileSync(file, 'utf8'))
    if (!loaded || typeof loaded !== 'object' || Array.isArray(loaded)) throw new Error('独立凭据文件格式错误')
    if (process.env.NOVEL_HELPER_CREDENTIAL_CODEC) {
      if(loaded.schema!=='novel-helper.dpapi.v1'||typeof loaded.protected!=='string') throw new Error('凭据保护格式错误，未读取明文或覆盖文件')
      values=JSON.parse(codec('decrypt',loaded.protected))
    } else values = loaded
    if(!values||typeof values!=='object'||Array.isArray(values)) throw new Error('独立凭据内容损坏，未覆盖文件')
  }
  let closed = false
  const key = ref => {
    if (typeof ref !== 'string' || !/^[A-Za-z0-9_.-]{1,200}$/.test(ref)) throw new TypeError('凭据引用无效')
    return ref
  }
  const save = next => {
    if (closed) throw new Error('凭据仓库已停止')
    const temp = `${file}.${process.pid}.${crypto.randomBytes(8).toString('hex')}.tmp`
    try {
      const saved=process.env.NOVEL_HELPER_CREDENTIAL_CODEC
        ? {schema:'novel-helper.dpapi.v1',protected:codec('encrypt',JSON.stringify(next))}:next
      fs.writeFileSync(temp, JSON.stringify(saved, null, 2), { mode: 0o600, flag: 'wx' })
      fs.renameSync(temp, file)
      values = next
    } finally { if (fs.existsSync(temp)) fs.unlinkSync(temp) }
  }
  return {
    async resolve(ref) {
      const value = values[key(ref)]
      return typeof value === 'string' ? { value, source: 'local' } : undefined
    },
    async describe(ref) { return { source: typeof values[key(ref)] === 'string' ? 'local' : undefined } },
    async set(ref, value) {
      if (typeof value !== 'string') throw new TypeError('凭据必须为字符串')
      save({ ...values, [key(ref)]: value })
    },
    async unset(ref) {
      const next = { ...values }
      delete next[key(ref)]
      save(next)
    },
    dispose() { closed = true; values = {} },
  }
}

function codec(mode,value) {
 const result=spawnSync(process.env.NOVEL_HELPER_PYTHON,[process.env.NOVEL_HELPER_CREDENTIAL_CODEC,mode],
  {input:value,encoding:'utf8',windowsHide:true,timeout:15000,maxBuffer:16*1024*1024})
 if(result.error||result.status!==0)throw new Error('凭据加密不可用，未保存明文')
 return result.stdout
}
