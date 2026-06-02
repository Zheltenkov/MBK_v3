// API-клиент к FastAPI-бэкенду. Все запросы идут на тот же origin через nginx-proxy в проде
// или Vite-proxy в dev. SSE через нативный EventSource.

const SESSION_KEY = 'mbk_session_id';

export function loadSessionId() {
  try { return sessionStorage.getItem(SESSION_KEY); } catch { return null; }
}

export function saveSessionId(id) {
  try { sessionStorage.setItem(SESSION_KEY, id); } catch { /* приватный режим */ }
}

export function clearSessionId() {
  try { sessionStorage.removeItem(SESSION_KEY); } catch { /* */ }
}

async function jsonFetch(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let detail;
    try { detail = (await res.json()).detail; } catch { detail = res.statusText; }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

export async function getHealth() {
  return jsonFetch('/api/health');
}

export async function createSession(anketa) {
  return jsonFetch('/api/session', {
    method: 'POST',
    body: JSON.stringify({ anketa }),
  });
}

export async function getSessionState(sessionId) {
  return jsonFetch(`/api/session/${sessionId}`);
}

export async function getSessionUsage(sessionId) {
  return jsonFetch(`/api/session/${sessionId}/usage`);
}

export async function endSession(sessionId) {
  return jsonFetch(`/api/session/${sessionId}/end`, { method: 'POST' });
}

/**
 * Открывает SSE-стрим. Если message пустой/null, бэкенд понимает это как opening (если
 * история пуста). Иначе — обычный ход.
 *
 * callbacks: { onChunk, onBubbles, onState, onError, onDone }
 * Возвращает функцию-cancel для досрочного закрытия.
 */
export function streamMessage(sessionId, message, callbacks) {
  const url = new URL(`/api/session/${sessionId}/stream`, window.location.origin);
  if (message && message.trim()) url.searchParams.set('message', message);
  const es = new EventSource(url.toString());

  es.addEventListener('chunk', (e) => {
    try { callbacks.onChunk?.(JSON.parse(e.data)); } catch (err) { console.warn('bad chunk', err); }
  });
  es.addEventListener('bubbles', (e) => {
    try { callbacks.onBubbles?.(JSON.parse(e.data)); } catch (err) { console.warn('bad bubbles', err); }
  });
  es.addEventListener('state', (e) => {
    try { callbacks.onState?.(JSON.parse(e.data)); } catch (err) { console.warn('bad state', err); }
  });
  // Серверное событие error (отличается от нативной ошибки соединения).
  es.addEventListener('error', (e) => {
    // Если у события есть .data — это сервер прислал прикладную ошибку.
    if (e.data) {
      try { callbacks.onError?.(JSON.parse(e.data)); } catch { callbacks.onError?.({ message: 'unknown server error' }); }
    }
    // Иначе это транспортная ошибка EventSource (например, обрыв). Обработаем в onerror.
  });
  es.addEventListener('done', () => {
    callbacks.onDone?.();
    es.close();
  });

  // Транспортная ошибка соединения.
  es.onerror = () => {
    // Если соединение закрылось нормально (после done), readyState=CLOSED — это ОК.
    if (es.readyState === EventSource.CLOSED) return;
    callbacks.onError?.({ message: 'Соединение прервано. Попробуйте ещё раз.' });
    es.close();
  };

  return () => es.close();
}
