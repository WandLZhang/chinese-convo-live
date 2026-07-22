import {
  getAuth,
  signInWithPopup,
  GoogleAuthProvider,
  type Auth,
  type User,
} from 'firebase/auth'
import { app } from './firebase'
import { appConfig } from './firebase.config'

const auth: Auth = getAuth(app)
const provider = new GoogleAuthProvider()

// Single-user app: nudge and hard-gate to the owner's account (from the gitignored config).
export const ALLOWED_EMAIL = appConfig.ownerEmail.toLowerCase()
provider.setCustomParameters({ login_hint: ALLOWED_EMAIL })

export async function signIn(): Promise<User> {
  const result = await signInWithPopup(auth, provider)
  const email = result.user.email?.toLowerCase()
  if (email !== ALLOWED_EMAIL) {
    console.error('Rejected sign-in for non-owner email:', email)
    await auth.signOut()
    throw new Error(`Please sign in with ${ALLOWED_EMAIL}`)
  }
  return result.user
}

export function onAuthChange(callback: (user: User | null) => void) {
  return auth.onAuthStateChanged(callback)
}
