// Copy this file to firebase.config.ts and fill in the values from your Firebase
// console (Project settings -> your web app). The web config is public-by-nature
// (it ships to the browser) but is gitignored so the repo stays project-agnostic.
export const firebaseConfig = {
  apiKey: 'your-api-key',
  authDomain: 'your-project.firebaseapp.com',
  projectId: 'your-project-id',
  storageBucket: 'your-project.firebasestorage.app',
  messagingSenderId: 'your-messaging-sender-id',
  appId: 'your-app-id',
}

// App-specific config (not part of the Firebase SDK). `ownerEmail` hard-gates this single-user
// app; `region` + `projectId` derive the Cloud Functions base URL (see firebase.ts).
export const appConfig = {
  ownerEmail: 'you@example.com',
  region: 'us-east4',
  // Speech-to-text runs on Cloud Run (SenseVoice needs ffmpeg + a 237MB model in the image), so it
  // has its own *.run.app URL rather than the derived cloudfunctions.net base.
  // scripts/deploy_transcribe.sh prints this after deploying.
  transcribeUrl: 'https://convo-live-transcribe-xxxxxxxx.us-east4.run.app/',
}
