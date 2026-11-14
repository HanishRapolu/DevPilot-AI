declare module 'diff' {
  export function parsePatch(text: string): Array<{newFileName?: string; hunks: Array<{oldStart: number; newStart: number; lines: string[]}>}>
}
