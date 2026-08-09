import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './index.css'

// NOTE: intentionally not wrapped in <StrictMode>. The app owns several
// singleton side-effecting resources (WebSocket, mic stream, <audio>
// element) that are created once in effects; StrictMode's dev-only
// double-invoke of effects is more risk than benefit for a demo build.
createRoot(document.getElementById('root')).render(<App />)
