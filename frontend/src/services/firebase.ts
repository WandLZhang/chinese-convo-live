import { initializeApp } from 'firebase/app'
import { getFirestore } from 'firebase/firestore'
import { getAuth } from 'firebase/auth'
import { firebaseConfig, appConfig } from './firebase.config'

export const app = initializeApp(firebaseConfig)
export const db = getFirestore(app)
export const auth = getAuth(app)
auth.useDeviceLanguage()

// Cloud Functions base URL, derived from the (gitignored) project config — no hardcoded ids.
export const functionBase = `https://${appConfig.region}-${firebaseConfig.projectId}.cloudfunctions.net`
