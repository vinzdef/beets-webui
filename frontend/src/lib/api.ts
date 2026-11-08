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

export interface Page<T> {
	total: number;
	offset: number;
	limit: number;
	results: T[];
}

async function get<T>(path: string, params: Record<string, string | number> = {}): Promise<T> {
	const qs = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]));
	const res = await fetch(`/api${path}${qs.size ? `?${qs}` : ''}`);
	if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
	return res.json();
}

export const api = {
	albums: (q = '', offset = 0, limit = 100) => get<Page<Album>>('/albums', { q, offset, limit }),
	album: (id: number) => get<Album & { items: Item[] }>(`/albums/${id}`),
	items: (q = '', offset = 0, limit = 100) => get<Page<Item>>('/items', { q, offset, limit }),
	artUrl: (id: number) => `/api/albums/${id}/art`
};
