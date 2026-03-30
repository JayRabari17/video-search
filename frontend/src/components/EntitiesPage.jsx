import React, { useEffect, useState } from 'react';
import { Image as ImageIcon, Plus, AlertCircle, CheckCircle } from 'lucide-react';
import { upload_to_s3 } from '../utils/s3Upload';
import { getPresignedUploadUrl, completeMultipartUpload, listEntities, createEntity } from '../services/api';
import EntityEditorModal from './EntityEditorModal';

const MAX_IMAGES = 10;

const EntitiesPage = () => {
  const [entities, setEntities] = useState([]);
  const [name, setName] = useState('');
  const [files, setFiles] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState('');
  const [activeEntityId, setActiveEntityId] = useState(null);

  const loadEntities = async () => {
    try {
      const data = await listEntities();
      setEntities(data.entities || []);
    } catch (e) {
      console.error('Failed to load entities', e);
      setError('Failed to load entities');
    }
  };

  useEffect(() => {
    loadEntities();
  }, []);

  const handleFileChange = (e) => {
    const selected = Array.from(e.target.files || []);
    const all = [...files, ...selected].slice(0, MAX_IMAGES);
    setFiles(all);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSuccess('');

    if (!name.trim()) {
      setError('Please enter a name for the entity.');
      return;
    }
    if (files.length < 1) {
      setError('Please upload at least 1 reference image for an entity.');
      return;
    }

    setIsSubmitting(true);
    try {
      const imageKeys = [];

      for (const file of files) {
        const presignedData = await getPresignedUploadUrl(file.name, file.size, 'entities', file.type);
        const uploadResult = await upload_to_s3(file, presignedData, () => {});

        let s3Key;
        if (uploadResult.type === 'multipart') {
          await completeMultipartUpload({
            uploadId: uploadResult.uploadId,
            s3_key: presignedData.s3_key,
            parts: uploadResult.parts,
          });
          s3Key = presignedData.s3_key;
        } else {
          s3Key = presignedData.s3_key;
        }

        imageKeys.push(s3Key);
      }
      await createEntity(name.trim(), imageKeys);

      setName('');
      setFiles([]);
      setSuccess('Entity created successfully.');
      await loadEntities();
    } catch (e) {
      console.error('Failed to create entity', e);
      setError(e.message || 'Failed to create entity');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="w-full max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-4">People & Entities</h1>
      <p className="text-gray-600 mb-6">
        Create named entities with reference images.<br/><br/>
        <span style={{ fontSize: '14px', color: 'gray' }}> <span className="font-bold">Note:</span> For now, consider the first image as the primary image for the entity.</span>
      </p>

      <form onSubmit={handleSubmit} className="mb-10 bg-white rounded-2xl shadow-sm border border-gray-200 p-6 space-y-4">
        {error && (
          <div className="flex items-center gap-2 text-red-700 bg-red-50 border border-red-200 rounded-xl px-3 py-2 mb-2">
            <AlertCircle size={18} />
            <span className="text-sm">{error}</span>
          </div>
        )}
        {success && (
          <div className="flex items-center gap-2 text-green-700 bg-green-50 border border-green-200 rounded-xl px-3 py-2 mb-2">
            <CheckCircle size={18} />
            <span className="text-sm">{success}</span>
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Entity name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            placeholder="e.g. Anna Smith"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Reference images <span className="text-gray-400">(up to {MAX_IMAGES})</span>
          </label>
          <input
            type="file"
            accept="image/jpeg,image/png,image/gif,image/webp"
            multiple
            onChange={handleFileChange}
            className="block w-full text-sm text-gray-600"
          />
          {files.length > 0 && (
            <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
              {files.map((file, index) => (
                <div
                  key={index}
                  className="border border-gray-200 rounded-xl p-2 flex flex-col items-center justify-center text-xs"
                >
                  <ImageIcon className="w-8 h-8 text-gray-400 mb-1" />
                  <span className="truncate max-w-[120px]">{file.name}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="pt-2">
          <button
            type="submit"
            disabled={isSubmitting}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            <Plus size={16} />
            {isSubmitting ? 'Creating...' : 'Create entity'}
          </button>
        </div>
      </form>

      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-3">Your entities</h2>
        {entities.length === 0 ? (
          <p className="text-sm text-gray-500">No entities created yet.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
            {entities.map((entity) => (
              <button
                key={entity.entity_id}
                type="button"
                onClick={() => setActiveEntityId(entity.entity_id)}
                className="text-left bg-white border border-gray-200 rounded-xl p-4 flex items-center gap-3 shadow-sm hover:border-gray-300 hover:shadow transition"
              >
                <div className="w-12 h-12 rounded-lg bg-gray-100 flex items-center justify-center overflow-hidden">
                  {entity.thumbnail_url ? (
                    <img
                      src={entity.thumbnail_url}
                      alt={entity.name}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <ImageIcon className="w-6 h-6 text-gray-400" />
                  )}
                </div>
                <div>
                  <div className="text-sm font-semibold text-gray-900">{entity.name}</div>
                  <div className="text-xs text-gray-500">{entity.entity_id}</div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      <EntityEditorModal
        open={Boolean(activeEntityId)}
        entityId={activeEntityId}
        onClose={() => setActiveEntityId(null)}
        onSaved={async () => {
          await loadEntities();
          setActiveEntityId(null);
        }}
        onDeleted={async () => {
          await loadEntities();
          setActiveEntityId(null);
        }}
      />
    </div>
  );
};

export default EntitiesPage;

