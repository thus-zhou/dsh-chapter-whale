/** Locked upstream independent runtime; never imports dsh configuration. */
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { startStandalone } from '../vendor/our-free-model-source/packages/standalone/service.mjs'
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const dataDir=path.join(root,'integration_data','ofm-home')
const marker=path.join(root,'integration_data','ofm-service.json')
const logger=Object.fromEntries(['info','warn','error'].map(level=>[level,()=>{}]))
try {
 const service=await startStandalone({dataDir,refresh:false,probe:false,lanEnabled:false,preservePrompts:true,logger})
 const info={product:'novel-helper-ofm',upstream_product:service.product,version:service.version,pid:process.pid,
  started_at:new Date().toISOString(),startup_id:crypto.randomUUID(),url:service.url,
  source_revision:'25151bab43ff28bfc0eef5a3dbec4443ecc6d2f2'}
 info.source_lock_sha256=crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'vendor/ofm-source-lock.json'))).digest('hex')
 const temp=marker+'.'+process.pid+'.tmp';fs.writeFileSync(temp,JSON.stringify(info),{mode:0o600});fs.renameSync(temp,marker)
 let closing=false
 const close=async()=>{if(closing)return;closing=true;await service.close()}
 process.once('SIGINT',()=>void close());process.once('SIGTERM',()=>void close())
} catch {
 // Do not serialize upstream errors: they can contain OAuth/session material.
 process.stderr.write('OFM independent runtime failed to start.\n');process.exitCode=1
}
