import fs from 'node:fs'
import path from 'node:path'

// Every filesystem path in the API is built from a request. Sanitising the
// segments is not enough — the check that matters is on the resolved path,
// after `..` and symlinks have collapsed. Callers get null and answer 404,
// identically to a missing file, so a probe cannot tell the two apart.
export function resolveWithin(root: string, ...segments: string[]): string | null {
  if (segments.some((s) => s === '' || s.includes('\0'))) return null
  const rootResolved = path.resolve(root)
  const candidate = path.resolve(rootResolved, ...segments)
  if (candidate !== rootResolved && !candidate.startsWith(rootResolved + path.sep)) return null
  return candidate
}

// Autosave fires on every keystroke, so a write is nearly always in flight when
// the process dies. Rename is atomic within a filesystem, so a reader sees either
// the previous file or the new one, never a truncated one. The temp file must be
// a sibling for the rename to stay within that filesystem.
export function writeFileAtomic(file: string, data: string): void {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  const tmp = `${file}.${process.pid}.${Math.random().toString(36).slice(2, 8)}.tmp`
  try {
    fs.writeFileSync(tmp, data)
    fs.renameSync(tmp, file)
  } catch (err) {
    fs.rmSync(tmp, { force: true })
    throw err
  }
}
