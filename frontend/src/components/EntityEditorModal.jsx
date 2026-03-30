import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle, Loader2, Plus, Trash2, X } from 'lucide-react';
import { upload_to_s3 } from '../utils/s3Upload';
import {
  completeMultipartUpload,
  deleteEntity,
  getEntity,
  getPresignedUploadUrl,
  updateEntity,
} from '../services/api';

const MAX_IMAGES = 10;

const EntityEditorModal = ({ open, entityId, onClose, onSaved, onDeleted }) => {
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState('');

  const [original, setOriginal] = useState(null);
  const [draftName, setDraftName] = useState('');
  const [existingKeys, setExistingKeys] = useState([]);
  const [removedKeys, setRemovedKeys] = useState(() => new Set());
  const [newFiles, setNewFiles] = useState([]);
  const [lightboxUrl, setLightboxUrl] = useState('');
  const [lightboxAlt, setLightboxAlt] = useState('');

  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saveSuccess, setSaveSuccess] = useState('');
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    if (!open || !entityId) return;
    let cancelled = false;

    const run = async () => {
      setIsLoading(true);
      setLoadError('');
      setSaveError('');
      setSaveSuccess('');
      try {
        const data = await getEntity(entityId);
        if (cancelled) return;
        setOriginal(data);
        setDraftName(data.name || '');
        setExistingKeys(data.image_keys || []);
        setRemovedKeys(new Set());
        setNewFiles([]);
        setLightboxUrl('');
        setLightboxAlt('');
      } catch (e) {
        if (cancelled) return;
        setLoadError(e.message || 'Failed to load entity');
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [open, entityId]);

  const currentImages = useMemo(() => {
    const existing = (original?.images || []).filter((img) => img?.key && !removedKeys.has(img.key));
    const added = newFiles.map((file, idx) => ({
      key: `__new__${idx}`,
      url: URL.createObjectURL(file),
      isNew: true,
      file,
    }));
    return [...existing, ...added];
  }, [original, removedKeys, newFiles]);

  const newIndexByKey = useMemo(() => {
    const map = new Map();
    for (let i = 0; i < newFiles.length; i++) {
      map.set(`__new__${i}`, i);
    }
    return map;
  }, [newFiles]);

  useEffect(() => {
    return () => {
      for (const img of currentImages) {
        if (img.isNew && img.url) URL.revokeObjectURL(img.url);
      }
    };
  }, [currentImages]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        if (lightboxUrl) {
          setLightboxUrl('');
          setLightboxAlt('');
        } else {
          resetAndClose();
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, lightboxUrl]);

  const remainingCount = useMemo(() => {
    const existingRemaining = existingKeys.filter((k) => k && !removedKeys.has(k)).length;
    return existingRemaining + newFiles.length;
  }, [existingKeys, removedKeys, newFiles]);

  const canSave = useMemo(() => {
    if (!open || !entityId) return false;
    if (isLoading || isSaving || isDeleting) return false;
    if (!draftName.trim()) return false;
    if (remainingCount < 1) return false;
    if (remainingCount > MAX_IMAGES) return false;
    return true;
  }, [open, entityId, isLoading, isSaving, isDeleting, draftName, remainingCount]);

  const resetAndClose = () => {
    setOriginal(null);
    setDraftName('');
    setExistingKeys([]);
    setRemovedKeys(new Set());
    setNewFiles([]);
    setLightboxUrl('');
    setLightboxAlt('');
    setLoadError('');
    setSaveError('');
    setSaveSuccess('');
    onClose?.();
  };

  const onPickFiles = (e) => {
    const selected = Array.from(e.target.files || []);
    if (selected.length === 0) return;
    setSaveError('');
    setSaveSuccess('');

    const room = Math.max(0, MAX_IMAGES - remainingCount);
    const toAdd = selected.slice(0, room);
    setNewFiles((prev) => [...prev, ...toAdd]);
    e.target.value = '';
  };

  const removeExisting = (key) => {
    setSaveError('');
    setSaveSuccess('');
    if (key && key === lightboxAlt) {
      setLightboxUrl('');
      setLightboxAlt('');
    }
    setRemovedKeys((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });
  };

  const removeNew = (idx) => {
    setSaveError('');
    setSaveSuccess('');
    if (lightboxAlt === `__new__${idx}`) {
      setLightboxUrl('');
      setLightboxAlt('');
    }
    setNewFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleSave = async () => {
    setSaveError('');
    setSaveSuccess('');
    if (!canSave) return;

    setIsSaving(true);
    try {
      // Upload newly added files to S3 and collect keys.
      const uploadedKeys = [];
      for (const file of newFiles) {
        const presignedData = await getPresignedUploadUrl(file.name, file.size, 'entities', file.type);
        const uploadResult = await upload_to_s3(file, presignedData, () => {});

        if (uploadResult.type === 'multipart') {
          await completeMultipartUpload({
            uploadId: uploadResult.uploadId,
            s3_key: presignedData.s3_key,
            parts: uploadResult.parts,
          });
        }
        uploadedKeys.push(presignedData.s3_key);
      }

      const keptExistingKeys = existingKeys.filter((k) => k && !removedKeys.has(k));
      const finalKeys = [...keptExistingKeys, ...uploadedKeys].slice(0, MAX_IMAGES);
      if (finalKeys.length < 1) {
        throw new Error('Please keep at least 1 image.');
      }

      await updateEntity(entityId, { name: draftName.trim(), image_keys: finalKeys });
      setSaveSuccess('Saved.');
      await onSaved?.();
    } catch (e) {
      setSaveError(e.message || 'Failed to save entity');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!entityId) return;
    const ok = window.confirm('Delete this entity? This cannot be undone.');
    if (!ok) return;
    setSaveError('');
    setSaveSuccess('');
    setIsDeleting(true);
    try {
      await deleteEntity(entityId);
      await onDeleted?.();
    } catch (e) {
      setSaveError(e.message || 'Failed to delete entity');
    } finally {
      setIsDeleting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={resetAndClose} />
      <div className="relative w-[95vw] max-w-4xl max-h-[90vh] overflow-hidden bg-white rounded-2xl shadow-xl border border-gray-200">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <div>
            <div className="text-lg font-semibold text-gray-900">Edit entity</div>
            <div className="text-xs text-gray-500 truncate max-w-[70vw]">{entityId}</div>
          </div>
          <button
            type="button"
            onClick={resetAndClose}
            className="p-2 rounded-xl hover:bg-gray-100 text-gray-600"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <div className="p-5 overflow-auto max-h-[calc(90vh-140px)]">
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-gray-600">
              <Loader2 className="animate-spin" size={16} />
              Loading…
            </div>
          ) : loadError ? (
            <div className="flex items-center gap-2 text-red-700 bg-red-50 border border-red-200 rounded-xl px-3 py-2">
              <AlertCircle size={18} />
              <span className="text-sm">{loadError}</span>
            </div>
          ) : (
            <>
              {saveError && (
                <div className="flex items-center gap-2 text-red-700 bg-red-50 border border-red-200 rounded-xl px-3 py-2 mb-3">
                  <AlertCircle size={18} />
                  <span className="text-sm">{saveError}</span>
                </div>
              )}
              {saveSuccess && (
                <div className="flex items-center gap-2 text-green-700 bg-green-50 border border-green-200 rounded-xl px-3 py-2 mb-3">
                  <CheckCircle size={18} />
                  <span className="text-sm">{saveSuccess}</span>
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Entity name</label>
                  <input
                    type="text"
                    value={draftName}
                    onChange={(e) => setDraftName(e.target.value)}
                    className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    placeholder="e.g. Anna Smith"
                  />
                  <div className="mt-2 text-xs text-gray-500">
                    Images: {remainingCount}/{MAX_IMAGES}
                  </div>
                </div>

                <div className="flex items-end justify-start gap-3">
                  <label className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 cursor-pointer">
                    <Plus size={16} />
                    Add images
                    <input
                      type="file"
                      className="hidden"
                      multiple
                      accept="image/jpeg,image/png,image/gif,image/webp"
                      onChange={onPickFiles}
                    />
                  </label>
                  <button
                    type="button"
                    onClick={handleDelete}
                    disabled={isDeleting || isSaving || isLoading}
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-xl border border-red-200 text-red-700 bg-white text-sm font-semibold hover:bg-red-50 disabled:opacity-60 disabled:cursor-not-allowed"
                  >
                    <Trash2 size={16} />
                    {isDeleting ? 'Deleting…' : 'Delete'}
                  </button>
                </div>
              </div>

              <div className="mt-5">
                {currentImages.length === 0 ? (
                  <div className="text-sm text-gray-500">No images.</div>
                ) : (
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
                    {currentImages.map((img) => {
                      const isNew = Boolean(img.isNew);
                      const remove = () => {
                        if (isNew) {
                          const idx = newIndexByKey.get(img.key);
                          if (typeof idx === 'number') removeNew(idx);
                          return;
                        }
                        removeExisting(img.key);
                      };
                      return (
                        <div key={img.key} className="relative group rounded-xl overflow-hidden border border-gray-200">
                          <button
                            type="button"
                            onClick={() => {
                              if (!img.url) return;
                              setLightboxUrl(img.url);
                              setLightboxAlt(img.key);
                            }}
                            className="block w-full"
                            aria-label="Enlarge image"
                          >
                            {img.url ? (
                              <img src={img.url} alt={img.key} className="w-full h-24 object-cover" />
                            ) : (
                              <div className="w-full h-24 bg-gray-100" />
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={remove}
                            className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition px-2 py-1 rounded-lg bg-white/90 border border-gray-200 text-xs text-gray-700 hover:bg-white"
                          >
                            Remove
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-gray-200 bg-gray-50">
          <button
            type="button"
            onClick={resetAndClose}
            disabled={isSaving || isDeleting}
            className="px-4 py-2 rounded-xl border border-gray-300 bg-white text-gray-800 text-sm font-semibold hover:bg-gray-100 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!canSave}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {isSaving ? <Loader2 className="animate-spin" size={16} /> : null}
            {isSaving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      {lightboxUrl ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/70"
            onClick={() => {
              setLightboxUrl('');
              setLightboxAlt('');
            }}
          />
          <div className="relative w-[92vw] max-w-5xl max-h-[88vh] bg-white rounded-2xl shadow-2xl border border-gray-200 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
              <div className="text-sm font-semibold text-gray-900 truncate">{lightboxAlt || 'Image'}</div>
              <button
                type="button"
                onClick={() => {
                  setLightboxUrl('');
                  setLightboxAlt('');
                }}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-blue-600 text-white hover:bg-blue-700 text-white text-sm font-semibold"
              >
                <X size={16} />
                Close
              </button>
            </div>
            <div className="bg-black flex items-center justify-center">
              <img
                src={lightboxUrl}
                alt={lightboxAlt || 'Entity image'}
                className="max-h-[calc(88vh-56px)] w-auto object-contain"
              />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default EntityEditorModal;

