export interface Item {
	id: number;
	title: string;
	artist: string;
	album: string;
	track: number;
	length: number;
	path: string | null;
	[field: string]: unknown;
}

export interface Album {
	id: number;
	album: string;
	albumartist: string;
	year: number;
	artpath: string | null;
	/** The album's folder, relative to the library folder when it's inside it. */
	folder: string | null;
	[field: string]: unknown;
}

export type AlbumOrder = 'default' | 'artist' | 'album' | 'path';

export interface Page<T> {
	total: number;
	offset: number;
	limit: number;
	results: T[];
}

async function get<T>(path: string, params: Record<string, string | number> = {}): Promise<T> {
	const qs = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]));
	const res = await fetch(`/api${path}${qs.size ? `?${qs}` : ''}`);
	if (!res.ok) {
		const detail = await res.json().catch(() => null);
		throw new Error(detail?.detail ?? `${res.status} ${res.statusText}`);
	}
	return res.json();
}

export const api = {
	albums: (q = '', order: AlbumOrder = 'default', offset = 0, limit = 100) =>
		get<Page<Album>>('/albums', { q, order, offset, limit }),
	album: (id: number) => get<Album & { items: Item[] }>(`/albums/${id}`),
	items: (q = '', offset = 0, limit = 100) => get<Page<Item>>('/items', { q, offset, limit }),
	artUrl: (id: number) => `/api/albums/${id}/art`,
	/** Like `beet update`: drops entries whose files are gone and re-reads changed tags. */
	previewUpdate: () => get<LibraryUpdatePreview>('/library/update'),
	updateLibrary: () => post<LibraryUpdate>('/library/update')
};

export interface LibraryUpdatePreview {
	missing: Pick<Item, 'id' | 'artist' | 'album' | 'title' | 'path'>[];
	/** Whether files whose tags changed get moved to match the path format. */
	moves_files: boolean;
}

export interface LibraryUpdate {
	removed_items: number;
	removed_albums: number;
}

// Imports

export interface InboxEntry {
	name: string;
	path: string;
	is_dir: boolean;
}

export interface Inbox {
	name: string;
	path: string;
	exists: boolean;
	entries: InboxEntry[];
}

export interface ImportItem {
	path: string;
	title: string;
	artist: string;
	album: string;
	track: number;
	disc: number;
	length: number;
	format: string;
	bitrate: number;
}

export interface ImportTrack {
	title: string | null;
	artist: string | null;
	index: number | null;
	medium: number | null;
	medium_index: number | null;
	length: number | null;
}

export interface Candidate {
	index: number;
	distance: number;
	similarity: number;
	strength: 'strong' | 'medium' | 'weak';
	penalties: string[];
	disambig: string;
	artist: string;
	name: string;
	id: string | null;
	data_source: string | null;
	// Albums
	year?: number | null;
	label?: string | null;
	country?: string | null;
	media?: string | null;
	albumtype?: string | null;
	tracks?: { item: ImportItem; track: ImportTrack }[];
	extra_items?: ImportItem[];
	extra_tracks?: ImportTrack[];
	// Singletons
	album?: string | null;
	length?: number | null;
}

export interface ImportTask {
	kind: 'album' | 'track';
	paths: string[];
	artist: string;
	name: string;
	items: ImportItem[];
}

export interface MatchQuestion {
	id: number;
	kind: 'match';
	task: ImportTask;
	recommendation: string;
	candidates: Candidate[];
	choices: { short: string; long: string }[];
}

export interface DuplicateQuestion {
	id: number;
	kind: 'duplicate';
	task: ImportTask;
	existing: { summary: string; description: string }[];
	new: string;
	options: { value: string; label: string }[];
}

export interface ResumeQuestion {
	id: number;
	kind: 'resume';
	path: string;
}

export type Question = MatchQuestion | DuplicateQuestion | ResumeQuestion;

export interface LogEntry {
	time: number;
	kind: string;
	message: string;
	level?: string;
	album_id?: number;
	item_id?: number;
}

export interface ImportJob {
	status: 'running' | 'waiting' | 'done' | 'aborted' | 'failed';
	paths: string[];
	options: Record<string, boolean>;
	error: string | null;
	started: number;
	finished: number | null;
	question: Question | null;
	log: LogEntry[];
}

/**
 * auto: apply matches above the configured strong-match threshold unasked;
 * manual: apply only perfect (100%) matches unasked; timid: ask about every match.
 */
export type ImportMode = 'auto' | 'manual' | 'timid';

export interface StartOptions {
	mode?: ImportMode;
	singletons?: boolean;
	group_albums?: boolean;
}

export type AnswerBody =
	| { type: 'apply'; candidate: number }
	| { type: 'choice'; short: string }
	| { type: 'search'; artist: string; name: string }
	| { type: 'id'; ids: string }
	| { type: 'duplicate'; action: string }
	| { type: 'resume'; resume: boolean };

async function post<T>(path: string, body: unknown = {}): Promise<T> {
	const res = await fetch(`/api${path}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	if (!res.ok) {
		const detail = await res.json().catch(() => null);
		throw new Error(detail?.detail ?? `${res.status} ${res.statusText}`);
	}
	return res.json();
}

export const imports = {
	inboxes: () => get<{ inboxes: Inbox[] }>('/inboxes'),
	start: (paths: string[], options: StartOptions) =>
		post<ImportJob>('/imports', { paths, ...options }),
	answer: (question: number, body: AnswerBody) =>
		post('/imports/current/answer', { question, ...body }),
	abort: () => post('/imports/current/abort'),
	/** Calls `onJob` with the current job (or null) now and whenever it changes. */
	subscribe(onJob: (job: ImportJob | null) => void): () => void {
		const source = new EventSource('/api/imports/current/events');
		source.onmessage = (e) => onJob(JSON.parse(e.data));
		return () => source.close();
	}
};

/** Similarity to one decimal (99.88 → "99.9"); only an exact match shows "100.0". */
export function formatSimilarity(candidate: { distance: number }): string {
	const value = Math.round((1 - candidate.distance) * 1000) / 10;
	return (candidate.distance > 0 && value >= 100 ? 99.9 : value).toFixed(1);
}

export function formatLength(seconds: number | null | undefined): string {
	if (seconds == null) return '';
	const s = Math.round(seconds);
	return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
