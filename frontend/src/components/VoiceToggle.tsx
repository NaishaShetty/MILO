// VoiceToggle.tsx -- the on/off switch for browser voice, with the fallback reason.
import { useBrowserVoice } from "../state/BrowserVoice";

export function VoiceToggle() {
  const voice = useBrowserVoice();
  const usable = voice.canListen || voice.canSpeak;
  return (
    <div className="voice-toggle">
      <label>
        <input
          type="checkbox"
          checked={voice.enabled && usable}
          disabled={!usable}
          onChange={(e) => voice.setEnabled(e.target.checked)}
        />{" "}
        Talk with MILO
      </label>
      {voice.unsupported && <span className="muted"> {voice.unsupported}</span>}
      {voice.listening && (
        <span className="pill" role="status">
          Listening...
        </span>
      )}
    </div>
  );
}
