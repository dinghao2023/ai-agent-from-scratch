<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from "vue";

interface Msg {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}
interface Approval {
  question: string;
  to?: string;
  subject?: string;
  body?: string;
}

const API = "http://127.0.0.1:8000";
const KEY_STORAGE = "api_key";
const THREAD_STORAGE = "thread_id";

const apiKey = ref(localStorage.getItem(KEY_STORAGE) || "");
const threadId = ref(localStorage.getItem(THREAD_STORAGE) || "");
const messages = ref<Msg[]>([]);
const input = ref("");
const loading = ref(false);
const approval = ref<Approval | null>(null);
const listEl = ref<HTMLElement>();

const canSend = computed(() => !loading.value && !approval.value);

function scrollBottom() {
  nextTick(() => listEl.value?.scrollTo(0, listEl.value.scrollHeight));
}

function rememberThread(id: string) {
  threadId.value = id;
  localStorage.setItem(THREAD_STORAGE, id);
}

function ensureKey(): boolean {
  if (apiKey.value) return true;
  const k = prompt("请输入 API Key");
  if (!k) return false;
  apiKey.value = k.trim();
  localStorage.setItem(KEY_STORAGE, apiKey.value);
  return true;
}

function resetKey() {
  apiKey.value = "";
  localStorage.removeItem(KEY_STORAGE);
}

async function errorText(resp: Response): Promise<string> {
  try {
    const data = await resp.json();
    if (typeof data.detail === "string") return data.detail;
    return JSON.stringify(data);
  } catch {
    return `请求失败（${resp.status}）`;
  }
}

function failBubble(bubble: Msg, text: string) {
  bubble.content = bubble.content
    ? `${bubble.content}\n\n${text}`
    : text;
  bubble.streaming = false;
}

async function loadHistory() {
  if (!threadId.value) {
    rememberThread(crypto.randomUUID().slice(0, 8));
  }
  if (!ensureKey()) return;
  const resp = await fetch(`${API}/sessions/${threadId.value}/messages`, {
    headers: { "X-API-Key": apiKey.value },
  });
  if (resp.status === 401) {
    resetKey();
    return;
  }
  if (!resp.ok) return;
  const data = await resp.json();
  messages.value = (data.items || []).map((m: { role: Msg["role"]; content: string }) => ({
    role: m.role,
    content: m.content,
  }));
  scrollBottom();
}

async function consumeStream(resp: Response, bubble: Msg) {
  if (!resp.ok) {
    if (resp.status === 401) resetKey();
    failBubble(bubble, await errorText(resp));
    return;
  }
  const reader = resp.body?.getReader();
  if (!reader) {
    failBubble(bubble, "没有收到流式响应");
    return;
  }
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.replace(/^data: /, "").trim();
      if (!line) continue;
      const data = JSON.parse(line);
      if (data.token) {
        bubble.content += data.token;
        scrollBottom();
      } else if (data.event === "waiting_approval") {
        approval.value = data.approval;
      }
    }
  }
  if (!bubble.content && !approval.value) {
    bubble.content = "没有收到回复";
  }
  bubble.streaming = false;
}

async function send() {
  const text = input.value.trim();
  if (!text || !canSend.value || !ensureKey()) return;
  input.value = "";
  messages.value.push({ role: "user", content: text });
  const bubble: Msg = { role: "assistant", content: "", streaming: true };
  messages.value.push(bubble);
  loading.value = true;
  scrollBottom();

  try {
    const resp = await fetch(`${API}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": apiKey.value },
      body: JSON.stringify({ thread_id: threadId.value, message: text }),
    });
    await consumeStream(resp, bubble);
  } catch (e) {
    failBubble(bubble, "请求失败：" + e);
  }
  loading.value = false;
  scrollBottom();
}

async function decide(decision: string) {
  if (!approval.value || loading.value) return;
  approval.value = null;
  const bubble: Msg = { role: "assistant", content: "", streaming: true };
  messages.value.push(bubble);
  loading.value = true;
  try {
    const resp = await fetch(`${API}/chat/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": apiKey.value },
      body: JSON.stringify({ thread_id: threadId.value, decision }),
    });
    if (!resp.ok) {
      if (resp.status === 401) resetKey();
      failBubble(bubble, await errorText(resp));
    } else {
      const data = await resp.json();
      if (data.status === "waiting_approval") {
        approval.value = data.approval;
        bubble.content = data.approval?.question || "仍在等待确认";
      } else {
        bubble.content = data.reply || "已处理";
      }
      bubble.streaming = false;
    }
  } catch (e) {
    failBubble(bubble, "请求失败：" + e);
  }
  loading.value = false;
  scrollBottom();
}

function newChat() {
  if (loading.value) return;
  rememberThread(crypto.randomUUID().slice(0, 8));
  messages.value = [];
  approval.value = null;
  input.value = "";
}

onMounted(loadHistory);
</script>

<template>
  <div class="page">
    <header>
      <span>My Agent</span>
      <span class="tid">会话 {{ threadId }}</span>
      <button class="new" :disabled="loading" @click="newChat">新会话</button>
    </header>

    <main ref="listEl" class="list">
      <p v-if="!messages.length && !approval" class="empty">
        问一个问题，或让它发一封邮件。发信前会停下来等你确认。
      </p>
      <div
        v-for="(m, i) in messages"
        :key="i"
        class="row"
        :class="m.role"
      >
        <div class="bubble">
          {{ m.content }}<span v-if="m.streaming" class="cursor">▍</span>
        </div>
      </div>

      <div v-if="approval" class="row assistant">
        <div class="bubble approval-card">
          <p>{{ approval.question }}</p>
          <p v-if="approval.to" class="draft">收件人：{{ approval.to }}</p>
          <p v-if="approval.subject" class="draft">主题：{{ approval.subject }}</p>
          <p v-if="approval.body" class="draft">{{ approval.body }}</p>
          <div class="btns">
            <button class="ok" :disabled="loading" @click="decide('确认')">确认发送</button>
            <button class="no" :disabled="loading" @click="decide('取消')">取消</button>
          </div>
        </div>
      </div>
    </main>

    <footer>
      <input
        v-model="input"
        :disabled="!canSend"
        :placeholder="approval ? '请先处理上方的发信确认' : '问点什么… 比如：帮我查一下今天的 AI 新闻'"
        @keyup.enter="send"
      />
      <button :disabled="!canSend" @click="send">发送</button>
    </footer>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-width: 760px;
  margin: 0 auto;
  background: #fff;
}
header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid #eee;
  font-weight: 600;
}
.tid {
  color: #999;
  font-size: 12px;
  font-weight: 400;
}
.new {
  margin-left: auto;
  border: 1px solid #ddd;
  background: #fff;
  border-radius: 8px;
  padding: 6px 12px;
  cursor: pointer;
}
.new:disabled {
  opacity: 0.5;
  cursor: default;
}
.list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.empty {
  color: #888;
  text-align: center;
  margin-top: 32px;
}
.row {
  display: flex;
  margin-bottom: 12px;
}
.row.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 75%;
  padding: 10px 14px;
  border-radius: 12px;
  white-space: pre-wrap;
  line-height: 1.6;
  background: #f2f3f5;
  text-align: left;
}
.row.user .bubble {
  background: #4f7cff;
  color: #fff;
}
.cursor {
  animation: blink 1s infinite;
}
@keyframes blink {
  50% { opacity: 0; }
}
.approval-card {
  border: 1px solid #f0a020;
  background: #fffaf0;
}
.draft {
  color: #666;
  font-size: 13px;
  border-left: 3px solid #ddd;
  padding-left: 8px;
  margin-top: 8px;
}
.btns {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.ok,
.no {
  border: none;
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
}
.ok {
  background: #18a058;
  color: #fff;
}
.no {
  background: #eee;
}
.ok:disabled,
.no:disabled {
  opacity: 0.5;
  cursor: default;
}
footer {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #eee;
}
input {
  flex: 1;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 8px;
}
footer button {
  padding: 0 20px;
  border: none;
  border-radius: 8px;
  background: #4f7cff;
  color: #fff;
  cursor: pointer;
}
footer button:disabled,
input:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
