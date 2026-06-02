import { useEffect, useState } from 'react';
import LandingScreen from './components/LandingScreen.jsx';
import AnketaForm from './components/AnketaForm.jsx';
import ChatView from './components/ChatView.jsx';
import { clearSessionId, createSession, getSessionState, loadSessionId, saveSessionId } from './api.js';

const SCREEN = { LANDING: 'landing', ANKETA: 'anketa', CHAT: 'chat' };

export default function App() {
  const [screen, setScreen] = useState(SCREEN.LANDING);
  const [sessionId, setSessionId] = useState(null);
  const [initialState, setInitialState] = useState(null);
  const [bootError, setBootError] = useState(null);
  const [booting, setBooting] = useState(true);

  // На старте — пытаемся восстановить сессию из sessionStorage.
  useEffect(() => {
    let cancelled = false;
    const stored = loadSessionId();
    if (!stored) {
      setBooting(false);
      return;
    }
    (async () => {
      try {
        const { state } = await getSessionState(stored);
        if (cancelled) return;
        setSessionId(stored);
        setInitialState(state);
        setScreen(SCREEN.CHAT);
      } catch {
        // 404 или другая ошибка — сессию серверная сторона не помнит, начинаем с нуля.
        clearSessionId();
      } finally {
        if (!cancelled) setBooting(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const startChat = async (anketa) => {
    setBootError(null);
    try {
      const { session_id, state } = await createSession(anketa);
      saveSessionId(session_id);
      setSessionId(session_id);
      setInitialState(state);
      setScreen(SCREEN.CHAT);
    } catch (e) {
      setBootError(e.message || String(e));
    }
  };

  const resetSession = () => {
    clearSessionId();
    setSessionId(null);
    setInitialState(null);
    setScreen(SCREEN.LANDING);
  };

  if (booting) {
    return <FullPageSpinner label="Открываем сессию…" />;
  }

  return (
    <div className="h-full flex flex-col">
      <Header onReset={screen === SCREEN.CHAT ? resetSession : null} />
      <main className="flex-1 overflow-hidden">
        {screen === SCREEN.LANDING && (
          <LandingScreen
            onChooseAnketa={() => setScreen(SCREEN.ANKETA)}
            onSkipAnketa={() => startChat(null)}
            error={bootError}
          />
        )}
        {screen === SCREEN.ANKETA && (
          <AnketaForm
            onCancel={() => setScreen(SCREEN.LANDING)}
            onSubmit={(anketa) => startChat(anketa)}
            submitError={bootError}
          />
        )}
        {screen === SCREEN.CHAT && sessionId && (
          <ChatView sessionId={sessionId} initialState={initialState} onReset={resetSession} />
        )}
      </main>
    </div>
  );
}

function Header({ onReset }) {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-xl">💬</span>
          <span className="font-semibold text-slate-800">МБК — Ассистент</span>
        </div>
        {onReset && (
          <button onClick={onReset} className="text-sm text-slate-500 hover:text-slate-700">
            Новая сессия
          </button>
        )}
      </div>
    </header>
  );
}

function FullPageSpinner({ label }) {
  return (
    <div className="h-full flex items-center justify-center text-slate-500">
      <div className="flex items-center gap-2">
        <Spinner />
        <span>{label}</span>
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <svg className="h-5 w-5 animate-spin text-brand-600" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
    </svg>
  );
}
