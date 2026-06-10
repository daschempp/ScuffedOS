/* Scuffed OS — offline capture mode (review D4).
   When the backend (or the assistant) is unreachable, the chat panel stops
   pretending: no canned replies, no invented figures. We try to file the
   message as a second-brain note and tell the user exactly what happened. */
import { api } from '../lib/api.js'

export async function captureReply(text) {
  try {
    await api.createMemory(text, { src: 'note' })
    return {
      text: "I'm offline right now, so I can't act on that — but I've saved it to your second brain and you can ask me again once I'm back.",
      action: { icon: 'brain', title: 'Captured while offline', meta: 'Saved to memory', cta: 'Open brain', screen: 'memory' },
    }
  } catch {
    return {
      text: "I can't reach the backend at all, so this message only lives in this window. Start the backend and resend anything important.",
      action: null,
    }
  }
}
