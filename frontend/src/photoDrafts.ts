type Photo = { id: string; move: string; file: File };
function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('moving-photo-drafts', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('photos', { keyPath: ['move', 'id'] });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function change(action: (store: IDBObjectStore) => void) {
  const db = await open();
  try { await new Promise<void>((resolve, reject) => {
    const transaction = db.transaction('photos', 'readwrite');
    transaction.oncomplete = () => resolve();
    transaction.onerror = transaction.onabort = () => reject(transaction.error);
    action(transaction.objectStore('photos'));
  }); } finally { db.close(); }
}
export const storePhoto = (move: string, id: string, file: File) => change(store => { store.put({ move, id, file }); });
export const removePhoto = (move: string, id: string) => change(store => { store.delete([move, id]); });
export async function savedPhotos(move: string): Promise<Photo[]> {
  const db = await open();
  try { return await new Promise<Photo[]>((resolve, reject) => {
    const request = db.transaction('photos').objectStore('photos').getAll(IDBKeyRange.bound([move, ''], [move, '\uffff']));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  }); } finally { db.close(); }
}
