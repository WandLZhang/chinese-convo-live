import { useEffect, useState } from 'react'
import { AuthProvider, useAuth } from './context/AuthContext'
import { useConversation } from './hooks/useConversation'
import ConversationView from './components/ConversationView'
import ChatInput from './components/ChatInput'
import OverflowMenu from './components/OverflowMenu'
import WordListDrawer from './components/WordListDrawer'
import { ALLOWED_EMAIL } from './services/auth'
import type { Language } from './types'

function Chat() {
  const { user, loading, error, signIn } = useAuth()
  const [language, setLanguage] = useState<Language>('mandarin')
  const [showWordList, setShowWordList] = useState(false)
  const [hadDifficulty, setHadDifficulty] = useState(false)
  const convo = useConversation({ language })

  // Start (or restart) the conversation on sign-in and whenever the language changes.
  useEffect(() => {
    if (user) void convo.start()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, language])

  if (loading) {
    return (
      <div className="app-frame center">
        <p className="muted">Loading…</p>
      </div>
    )
  }

  if (!user) {
    return (
      <div className="app-frame center">
        <div className="signin">
          <div className="signin-logo chinese-text">話</div>
          <h1>Chinese Convo Live</h1>
          <p className="muted">Sign in with {ALLOWED_EMAIL}</p>
          <button className="btn btn-primary" onClick={() => void signIn()}>
            Sign in with Google
          </button>
          {error && <p className="error">{error}</p>}
        </div>
      </div>
    )
  }

  const last = convo.turns[convo.turns.length - 1]
  const canAnswer =
    !convo.busy && last !== undefined && last.role === 'assistant' && last.question != null

  return (
    <div className="app-frame">
      <header className="top-app-bar">
        <span className="title">Chinese Convo Live</span>
        <div className="top-actions">
          <div className="lang-toggle">
            <button
              className={language === 'mandarin' ? 'active' : ''}
              onClick={() => setLanguage('mandarin')}
              aria-label="普通话 (Mandarin)"
            >
              普
            </button>
            <button
              className={language === 'cantonese' ? 'active' : ''}
              onClick={() => setLanguage('cantonese')}
              aria-label="廣東話 (Cantonese)"
            >
              粵
            </button>
          </div>
          <OverflowMenu
            onShuffle={() => void convo.shuffle()}
            onOpenWordList={() => setShowWordList(true)}
          />
        </div>
      </header>

      <ConversationView
        turns={convo.turns}
        language={language}
        onNext={() => void convo.next()}
        onMaster={() => void convo.masterCurrent()}
        onDifficulty={() => setHadDifficulty(true)}
        onUpdateReviewTime={(id, vocabId, iso) =>
          void convo.updateReviewTimeForTurn(id, vocabId, iso)
        }
      />

      <ChatInput
        language={language}
        disabled={!canAnswer}
        hadDifficulty={hadDifficulty}
        onHadDifficultyChange={setHadDifficulty}
        onSubmit={(a, d) => void convo.submitAnswer(a, d)}
      />

      {showWordList && (
        <WordListDrawer
          language={language}
          onClose={() => setShowWordList(false)}
          onPractice={(w) => void convo.practiceWord(w)}
        />
      )}
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <Chat />
    </AuthProvider>
  )
}
