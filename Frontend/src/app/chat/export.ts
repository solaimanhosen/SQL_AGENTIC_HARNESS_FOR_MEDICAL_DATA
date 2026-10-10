import { Injectable } from '@angular/core';

import { Answer } from '../api/types';

/**
 * Query rows as CSV, following RFC 4180: CRLF line ends, and quotes around any cell holding
 * a comma, a quote or a line break. A null is an empty cell.
 *
 * Text cells that a spreadsheet would run as a formula get a leading apostrophe. Stored text
 * is untrusted, and a cell such as =HYPERLINK(...) would otherwise act when the file is
 * opened. Numbers are left alone, including negative numbers stored as text.
 */
export function toCsv(columns: string[], rows: unknown[][]): string {
  const lines = [columns, ...rows].map((row) => row.map(csvCell).join(','));
  return lines.join('\r\n') + '\r\n';
}

function csvCell(value: unknown): string {
  if (value === null || value === undefined) {
    return '';
  }
  let text = typeof value === 'string' ? value : String(value);
  if (typeof value === 'string' && looksLikeFormula(text)) {
    text = `'${text}`;
  }
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function looksLikeFormula(text: string): boolean {
  if (/^[=@\t\r]/.test(text)) {
    return true;
  }
  return /^[+-]/.test(text) && !/^[+-]?\d+(\.\d+)?$/.test(text);
}

/** The answer exactly as the service sent it, rows included, for keeping as evidence. */
export function answerJson(answer: Answer): string {
  return JSON.stringify(answer, null, 2) + '\n';
}

/** A file name stem that ties a download to its conversation and question. */
export function fileStem(answer: Answer): string {
  return `${answer.conversation_id.slice(0, 8)}-turn${answer.turn}`;
}

/** Hands text to the browser as a file, and text to the clipboard. Replaced in tests. */
@Injectable({ providedIn: 'root' })
export class Exporter {
  save(name: string, text: string, type: string): void {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const link = document.createElement('a');
    link.href = url;
    link.download = name;
    link.click();
    URL.revokeObjectURL(url);
  }

  /** A byte order mark makes spreadsheets read the file as UTF-8. */
  saveCsv(name: string, csv: string): void {
    this.save(name, '﻿' + csv, 'text/csv;charset=utf-8');
  }

  /**
   * Copy text, reporting whether it worked. The clipboard API exists only on HTTPS and
   * localhost, so a page served over plain HTTP falls back to the older selection copy.
   */
  async copy(text: string): Promise<boolean> {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      return copyBySelection(text);
    }
  }
}

function copyBySelection(text: string): boolean {
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  try {
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    area.remove();
  }
}
