import { spawn } from 'node:child_process'

/**
 * Run a core script with the configured interpreter.
 *
 * Cancellation is cooperative: the harness signal kills the child process.
 * Non-zero exit codes are reported in the result, not thrown — the same
 * convention as the shipped bash tool, letting the model decide how to react.
 */
export function runPython(pythonPath, args, { signal } = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(pythonPath, args, { stdio: ['ignore', 'pipe', 'pipe'] })
    let stdout = ''
    let stderr = ''
    const onAbort = () => child.kill('SIGTERM')
    if (signal) {
      if (signal.aborted) onAbort()
      else signal.addEventListener('abort', onAbort, { once: true })
    }
    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (chunk) => {
      stdout += chunk
    })
    child.stderr.setEncoding('utf8')
    child.stderr.on('data', (chunk) => {
      stderr += chunk
    })
    child.on('error', (error) => {
      cleanup()
      reject(error)
    })
    child.on('close', (code, killSignal) => {
      cleanup()
      resolvePromise({
        exitCode: code ?? 1,
        stdout,
        stderr,
        killedBySignal: killSignal ?? null,
        aborted: Boolean(signal && signal.aborted),
      })
    })
    function cleanup() {
      if (signal && typeof signal.removeEventListener === 'function') {
        signal.removeEventListener('abort', onAbort)
      }
    }
  })
}
