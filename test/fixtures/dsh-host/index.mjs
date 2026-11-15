// Isolated-host test only. No HTTP model calls and no user credentials.
const { LlmAdapter } = await import(process.env.CHAPTER_WHALE_TEST_LLM_MODULE);
export const name = 'cw-host-fixture';
export const inject = ['llm', 'tools'];
export function apply(ctx) {
  ctx.tools.register({ name: 'novel_helper', description: 'Legacy coexistence fixture',
    parameters: { type: 'object', properties: {} },
    output: { schema: { type: 'object' }, render: () => [] }, execute: async () => ({ legacy: true }) });
  class Fixture extends LlmAdapter {
    providerInfo(id) { return { id, name: 'DSH 测试账号' }; }
    async listModels(provider) { return [{ provider, id: 'writer', name: '测试写作模型' }, { provider, id: 'editor', name: '测试审查模型' }]; }
    async resolveModel(provider, id) { return { provider, id, name: '测试模型' }; }
    async *stream(options) {
      if (options.tools?.length) {
        yield { type: 'tool-call-delta', index: 0, id: 'test-call', name: options.tools[0].name, argumentsDelta: '{}' };
      } else {
        const text = options.system.includes('JSON') ? '{"ok":true}' : '连接成功';
        yield { type: 'text-delta', index: 0, text };
      }
      yield { type: 'usage', usage: { inputTokens: 10, outputTokens: 5, totalTokens: 15 } };
      yield { type: 'finish', reason: { kind: options.tools?.length ? 'tool-calls' : 'stop' } };
    }
  }
  ctx.llm.registerAdapter(['cw-fixture'], new Fixture());
}
