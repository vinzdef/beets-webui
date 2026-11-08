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
	[field: string]: unknown;
}

/** Where an album's art comes from: beets' art file, an image in its folder, or a track's tags. */
export type ArtSource = 'file' | 'folder' | 'embedded';

export type AlbumDetail = Album & {
	items: Item[];
	art_source: ArtSource | null;
	/** Whether the mbsync plugin is on and the album is matched to a release. */
	can_refresh: boolean;
	problems: AlbumProblem[];
};

export type HealthCheck =
	'missing_files' | 'missing_tracks' | 'no_art' | 'unmatched' | 'duplicates';

/** The health checks, in the order the health details list them. */
export const HEALTH_CHECKS: { id: HealthCheck; label: string }[] = [
	{ id: 'missing_files', label: 'Missing files' },
	{ id: 'missing_tracks', label: 'Missing tracks' },
	{ id: 'no_art', label: 'No cover' },
	{ id: 'unmatched', label: 'Not matched' },
	{ id: 'duplicates', label: 'Duplicates' }
];

export interface AlbumProblem {
	id: HealthCheck;
	label: string;
	/** What exactly is wrong, e.g. which track numbers are missing. */
	detail: string;
	/** For duplicates: the other albums. */
	others?: Pick<Album, 'id' | 'album' | 'albumartist' | 'year'>[];
}

export interface AlbumEdit {
	album?: Record<string, string>;
	items?: Record<number, Record<string, string>>;
}

export type AlbumOrder = 'default' | 'artist' | 'album';

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
	/** `problem` keeps only albums failing that health check ('any' for any of them). */
	albums: (q = '', order: AlbumOrder = 'default', offset = 0, limit = 100, problem = '') =>
		get<Page<Album>>('/albums', { q, order, offset, limit, ...(problem && { problem }) }),
	album: (id: number) => get<AlbumDetail>(`/albums/${id}`),
	/** Like `beet modify`: changed fields as strings; album fields also apply to its tracks. */
	editAlbum: (id: number, edit: AlbumEdit) => post<AlbumDetail>(`/albums/${id}`, edit, 'PATCH'),
	items: (q = '', offset = 0, limit = 100) => get<Page<Item>>('/items', { q, offset, limit }),
	item: (id: number) => get<Item & { can_refresh: boolean }>(`/items/${id}`),
	/** Like `beet mbsync`: fetch the matched release (or recording) again and apply it. */
	refreshAlbum: (id: number) => post<AlbumDetail>(`/albums/${id}/refresh`),
	refreshItem: (id: number) => post<Item & { can_refresh: boolean }>(`/items/${id}/refresh`),
	editItem: (id: number, fields: Record<string, string>) =>
		post<Item>(`/items/${id}`, fields, 'PATCH'),
	/** Set the same fields on several albums or tracks. */
	editAlbums: (ids: number[], fields: Record<string, string>) =>
		post<{ updated: number }>('/albums', { ids, fields }, 'PATCH'),
	editItems: (ids: number[], fields: Record<string, string>) =>
		post<{ updated: number }>('/items', { ids, fields }, 'PATCH'),
	/** `version` busts the browser's cache after the art changed. */
	artUrl: (id: number, version = 0) => `/api/albums/${id}/art${version ? `?v=${version}` : ''}`,
	itemArtUrl: (id: number) => `/api/items/${id}/art`,
	fetchArt: (id: number) => post(`/albums/${id}/art/fetch`),
	saveArt: (id: number) => post(`/albums/${id}/art/save`),
	embedArt: (id: number) => post(`/albums/${id}/art/embed`),
	uploadArt: (id: number, image: Blob) => send(`/albums/${id}/art`, 'PUT', image),
	health: () => get<LibraryHealth>('/library/health'),
	/** What ftintitle would change: featured artists moved from the artist into the title. */
	previewFeat: () => get<FeatPreview>('/library/ftintitle'),
	moveFeat: (ids: number[]) => post<{ changed: number }>('/library/ftintitle', { ids }),
	coverFill: () => get<CoverFill>('/library/covers'),
	/** Give every album without an art file one: from its folder or tags, then fetchart. */
	fillCovers: (fetch: boolean) => post<CoverFill>('/library/covers', { fetch }),
	shrinkStatus: () => get<ShrinkArt>('/library/embedded-art'),
	/** Re-encode every track's embedded covers as JPEGs at most `max_width` pixels wide. */
	shrinkArt: (max_width: number, quality: number) =>
		post<ShrinkArt>('/library/embedded-art', { max_width, quality }),
	/** Like `beet update`: drops entries whose files are gone and re-reads changed tags. */
	previewUpdate: () => get<LibraryUpdatePreview>('/library/update'),
	updateLibrary: () => post<LibraryUpdate>('/library/update')
};

export interface LibraryUpdatePreview {
	missing: Pick<Item, 'id' | 'artist' | 'album' | 'title' | 'path'>[];
	/** Whether files whose tags changed get moved to match the path format. */
	moves_files: boolean;
}

export interface CoverFill {
	/** Whether the fetchart plugin is on, to look online. */
	can_fetch: boolean;
	running: boolean;
	// Absent before the first run.
	total?: number;
	done?: number;
	folder?: number;
	embedded?: number;
	fetched?: number;
	not_found?: Pick<Album, 'id' | 'album' | 'albumartist'>[];
}

export interface ShrinkArt {
	/** Whether the server can resize images (ImageMagick or Pillow). */
	can_resize: boolean;
	running: boolean;
	// Absent before the first run; counts are tracks.
	total?: number;
	done?: number;
	rewritten?: number;
	unchanged?: number;
	no_art?: number;
	failed?: number;
	saved_bytes?: number;
}

export interface FeatPreview {
	changes: {
		id: number;
		album_id: number | null;
		album: string;
		artist: string;
		title: string;
		new_artist: string;
		new_title: string;
	}[];
	/** Whether files are renamed to match their new titles. */
	moves_files: boolean;
}

export interface LibraryHealth {
	albums: number;
	healthy: number;
	checks: {
		id: HealthCheck;
		label: string;
		description: string;
		albums: Pick<Album, 'id' | 'album' | 'albumartist' | 'year'>[];
	}[];
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
	/** Where the track sits on the release; how a file is paired with it by hand. */
	pos: number;
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
	/** Whether beets numbers tracks per disc (else across the whole release). */
	per_disc_numbering: boolean;
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
	/** Which import the entry belongs to (in the full log). */
	job?: string;
	time: number;
	kind: string;
	message: string;
	level?: string;
	album_id?: number;
	item_id?: number;
	/** On "started" entries. */
	paths?: string[];
	reimport?: boolean;
}

export interface ImportJob {
	status: 'running' | 'waiting' | 'done' | 'aborted' | 'failed';
	/** Inbox paths, or for a re-import the album's name. */
	paths: string[];
	reimport: boolean;
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
	| {
			type: 'apply';
			candidate: number;
			keep_unmatched?: boolean;
			/** Files paired with tracks by hand: path -> track `pos`, or null if not on the release. */
			mapping?: Record<string, number | null>;
			/** Title and track number for kept files the release doesn't have, by path. */
			extra_tags?: Record<
				string,
				{ title: string | null; track: number | null; disc?: number | null }
			>;
	  }
	| { type: 'choice'; short: string }
	| { type: 'search'; artist: string; name: string }
	| { type: 'id'; ids: string }
	| { type: 'duplicate'; action: string }
	| { type: 'resume'; resume: boolean };

function post<T>(path: string, body: unknown = {}, method = 'POST'): Promise<T> {
	return send(path, method, JSON.stringify(body), { 'Content-Type': 'application/json' });
}

async function send<T>(
	path: string,
	method: string,
	body: BodyInit,
	headers: HeadersInit = {}
): Promise<T> {
	const res = await fetch(`/api${path}`, { method, headers, body });
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
	/** Re-import an album already in the library, to match it again without copying its files. */
	reimport: (albumId: number, options: StartOptions) =>
		post<ImportJob>('/imports', { album_id: albumId, ...options }),
	/** The same for a single track (not one on an album). */
	reimportItem: (itemId: number, options: StartOptions) =>
		post<ImportJob>('/imports', { item_id: itemId, ...options }),
	answer: (question: number, body: AnswerBody) =>
		post('/imports/current/answer', { question, ...body }),
	abort: () => post('/imports/current/abort'),
	/** Every import's log entries, newest first. */
	log: (offset = 0, limit = 1000) =>
		get<{ total: number; entries: LogEntry[] }>('/imports/log', { offset, limit }),
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

/** A field as text beets parses back: lists joined by "; ", zeros (unset numbers) blank. */
export function fieldText(value: unknown): string {
	if (Array.isArray(value)) return value.join('; ');
	if (value == null || value === 0) return '';
	return String(value);
}
