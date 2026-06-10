/* Scuffed OS — browser dictation (SpeechRecognition).
   Shared by the chat composer mic and the Home voice-note capture. Server-side
   Whisper is the planned fallback if browser quality disappoints (spec §1). */
import React from 'react'

const Recognition = typeof window !== 'undefined'
  ? (window.SpeechRecognition || window.webkitSpeechRecognition)
  : null

export const speechSupported = !!Recognition

export function useSpeech() {
  const [listening, setListening] = React.useState(false)
  const [transcript, setTranscript] = React.useState('')
  const recRef = React.useRef(null)
  const finalRef = React.useRef('')

  const stop = React.useCallback(() => {
    if (recRef.current) { recRef.current.onend = null; recRef.current.stop(); recRef.current = null }
    setListening(false)
  }, [])

  const start = React.useCallback(() => {
    if (!Recognition || recRef.current) return
    const rec = new Recognition()
    rec.continuous = true
    rec.interimResults = true
    rec.lang = navigator.language || 'en-US'
    finalRef.current = ''
    setTranscript('')
    rec.onresult = (e) => {
      let interim = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const piece = e.results[i][0].transcript
        if (e.results[i].isFinal) finalRef.current += piece
        else interim += piece
      }
      setTranscript((finalRef.current + interim).trim())
    }
    rec.onend = () => { recRef.current = null; setListening(false) }
    rec.onerror = () => { recRef.current = null; setListening(false) }
    rec.start()
    recRef.current = rec
    setListening(true)
  }, [])

  React.useEffect(() => stop, [stop]) // tear down on unmount

  return { supported: speechSupported, listening, transcript, setTranscript, start, stop }
}
