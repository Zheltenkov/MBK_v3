import { useEffect, useRef, useState } from 'react';
import { endSession, getSessionUsage, streamMessage } from '../api.js';

export default function ChatView({ sessionId, initialState, onReset }) {
  const [messages, setMessages] = useState(initialState?.chat_history || []);
  const [streamingBuffer, setStreamingBuffer] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [waitingExtraction, setWaitingExtraction] = useState(false);
  const [leadDelivered, setLeadDelivered] = useState(initialState?.lead_delivered || null);
  const [error, setError] = useState(null);
  const [showUsage, setShowUsage] = useState(false);
  const [usage, setUsage] = useState(null);

  const cancelRef = useRef(null);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const hasStartedOpeningRef = useRef(messages.length > 0);

  // Авто-старт opening, если истории ещё нет.
  useEffect(() => {
    if (!hasStartedOpeningRef.current) {
      hasStartedOpeningRef.current = true;
      runStream(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Авто-скролл к низу при новых сообщениях / стриме.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, streamingBuffer]);

  // Загрузка usage по запросу.
  useEffect(() => {
    if (!showUsage) return;
    let cancelled = false;
    getSessionUsage(sessionId).then((u) => { if (!cancelled) setUsage(u); }).catch(() => {});
    return () => { cancelled = true; };
  }, [showUsage, sessionId, messages.length]);

  const runStream = (userMessage) => {
    setError(null);
    setIsStreaming(true);
    setStreamingBuffer('');
    if (userMessage) {
      setMessages((m) => [...m, { role: 'user', content: userMessage }]);
    }
    const cancel = streamMessage(sessionId, userMessage || null, {
      onChunk: ({ text }) => setStreamingBuffer((b) => b + text),
      onBubbles: ({ bubbles }) => {
        // Сервер прислал финальную разбивку — заменяем накопленный буфер
        // на готовые пузыри (учитывают guard_bubbles).
        setStreamingBuffer('');
        setMessages((m) => [...m, ...bubbles.map((c) => ({ role: 'assistant', content: c }))]);
        setIsStreaming(false);
        setWaitingExtraction(userMessage ? true : false);
      },
      onState: ({ state, lead_delivered }) => {
        setWaitingExtraction(false);
        if (lead_delivered) setLeadDelivered(lead_delivered);
        if (state?.chat_history) setMessages(state.chat_history);
      },
      onError: ({ message }) => {
        setError(message || 'Ошибка');
        setIsStreaming(false);
        setWaitingExtraction(false);
        setStreamingBuffer('');
      },
      onDone: () => {
        setIsStreaming(false);
      },
    });
    cancelRef.current = cancel;
  };

  const handleSend = (e) => {
    e?.preventDefault();
    const text = inputRef.current?.value?.trim();
    if (!text || isStreaming) return;
    inputRef.current.value = '';
    runStream(text);
  };

  // Live-разбивка буфера на пузыри по \n\n. Последний пузырь — «растущий».
  const streamingBubbles = streamingBuffer
    ? streamingBuffer.split(/\n\n+/).map((s) => s.trim()).filter(Boolean)
    : [];

  const handleDownload = async () => {
    try {
      const u = await getSessionUsage(sessionId);
      const payload = {
        session_id: sessionId,
        chat_history: messages,
        lead_delivered: leadDelivered,
        usage: u,
        exported_at: new Date().toISOString(),
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `mbk_dialog_${sessionId}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message || String(err));
    }
  };

  const handleEnd = async () => {
    cancelRef.current?.();
    try { await endSession(sessionId); } catch {}
    onReset();
  };

  return (
    <div className="h-full flex flex-col">
      {/* Status bar: lead delivered / usage toggle */}
      {(leadDelivered || showUsage) && (
        <div className="mx-auto w-full max-w-3xl px-4 pt-3 space-y-2">
          {leadDelivered && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
              ✅ Заявка передана специалисту по направлению «{leadDelivered.product_label || leadDelivered.product_id}».
            </div>
          )}
          {showUsage && (
            <UsagePanel usage={usage} />
          )}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-4 py-4 space-y-3">
          {messages.length === 0 && !streamingBuffer && (
            <div className="text-center text-sm text-slate-400 py-12">
              Открываю чат…
            </div>
          )}
          {messages.map((m, i) => (
            <ChatBubble key={i} role={m.role} text={m.content} />
          ))}
          {streamingBubbles.map((b, i) => (
            <ChatBubble key={`s${i}`} role="assistant" text={b} streaming={i === streamingBubbles.length - 1} />
          ))}
          {waitingExtraction && <TypingIndicator label="Обновляю заявку" />}
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-slate-200 bg-white">
        <div className="mx-auto w-full max-w-3xl px-4 py-3">
          <form onSubmit={handleSend} className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              rows={1}
              placeholder={isStreaming ? 'Бот отвечает…' : 'Напишите сообщение…'}
              disabled={isStreaming && !waitingExtraction}
              className="input-base resize-none min-h-[44px] max-h-32"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
            />
            <button type="submit" disabled={isStreaming} className="btn-primary h-11">
              ↑
            </button>
          </form>
          <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
            <div className="flex gap-3">
              <button onClick={() => setShowUsage((s) => !s)} className="hover:text-slate-600">
                {showUsage ? 'Скрыть расходы' : 'Расходы и токены'}
              </button>
              <button onClick={handleDownload} className="hover:text-slate-600">Скачать диалог</button>
            </div>
            <button onClick={handleEnd} className="hover:text-slate-600">Завершить сессию</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ChatBubble({ role, text, streaming }) {
  const isUser = role === 'user';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} bubble-fade-in`}>
      <div
        className={`max-w-[85%] sm:max-w-[75%] rounded-2xl px-4 py-2 text-sm leading-relaxed whitespace-pre-wrap ${
          isUser
            ? 'bg-brand-600 text-white rounded-br-sm'
            : 'bg-white border border-slate-200 text-slate-800 rounded-bl-sm'
        }`}
      >
        {text}
        {streaming && <span className="inline-block w-1 h-4 ml-0.5 bg-slate-400 animate-pulse" />}
      </div>
    </div>
  );
}

function TypingIndicator({ label }) {
  return (
    <div className="flex items-center gap-2 text-xs text-slate-400 px-2">
      <span className="flex gap-1">
        <span className="typing-dot w-1.5 h-1.5 bg-slate-400 rounded-full" />
        <span className="typing-dot w-1.5 h-1.5 bg-slate-400 rounded-full" />
        <span className="typing-dot w-1.5 h-1.5 bg-slate-400 rounded-full" />
      </span>
      <span>{label}</span>
    </div>
  );
}

function UsagePanel({ usage }) {
  if (!usage) return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
      Загружаю расходы…
    </div>
  );
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700">
      <div className="flex justify-between font-medium text-slate-800">
        <span>Всего: {usage.total_tokens.toLocaleString('ru')} токенов</span>
        <span>${usage.total_cost_usd.toFixed(4)}</span>
      </div>
      <div className="mt-1 grid grid-cols-2 gap-x-4 gap-y-0.5 text-slate-500">
        {Object.entries(usage.by_role || {}).map(([role, v]) => (
          <div key={role} className="flex justify-between">
            <span>{translateRole(role)}:</span>
            <span>{v.prompt_tokens + v.completion_tokens} ток / ${v.cost_usd.toFixed(4)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function translateRole(r) {
  return { conversation: 'разговор', extraction: 'разбор', opening: 'старт' }[r] || r;
}
