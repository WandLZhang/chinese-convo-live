import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'
import type { User } from 'firebase/auth'
import { onAuthChange, signIn as doSignIn } from '../services/auth'

interface AuthState {
  user: User | null
  loading: boolean
  error: string | null
  signIn: () => Promise<void>
}

const AuthContext = createContext<AuthState | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const unsub = onAuthChange((u) => {
      setUser(u)
      setLoading(false)
    })
    return () => unsub()
  }, [])

  const signIn = async () => {
    setError(null)
    try {
      await doSignIn()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Sign-in failed')
    }
  }

  return (
    <AuthContext.Provider value={{ user, loading, error, signIn }}>
      {children}
    </AuthContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
