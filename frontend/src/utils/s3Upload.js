/**
 * Upload a file to S3 using a streaming chunk approach.
 * This avoids memory crashes by using file.slice() instead of arrayBuffer().
 */
export const upload_to_s3 = async (file, presignedData, onProgress) => {
  const { presigned_urls, uploadId, s3_path, presigned_url } = presignedData;

  // CASE 1: MULTIPART UPLOAD (Recommended for large files)
  if (presigned_urls && Array.isArray(presigned_urls)) {
    const CHUNK_SIZE = 10 * 1024 * 1024; // 10MB chunks
    const totalParts = presigned_urls.length;
    const partsMetadata = [];

    for (let i = 0; i < totalParts; i++) {
      const start = i * CHUNK_SIZE;
      const end = Math.min(start + CHUNK_SIZE, file.size);
      const chunk = file.slice(start, end); // Does not load into RAM

      const response = await fetch(presigned_urls[i], {
        method: 'PUT',
        body: chunk,
      });

      if (!response.ok) throw new Error(`Chunk ${i + 1} failed to upload.`);

      // S3 returns an ETag header which is required to complete the upload
      const etag = response.headers.get('ETag');
      if (!etag) {
        throw new Error(
          `Chunk ${i + 1} uploaded but ETag header was not readable. ` +
          `This is usually an S3 CORS issue: ensure the bucket CORS exposes the 'ETag' header.`
        );
      }
      partsMetadata.push({
        ETag: etag.replace(/"/g, ''),
        PartNumber: i + 1,
      });

      if (onProgress) {
        onProgress(Math.round(((i + 1) / totalParts) * 100));
      }
    }

    return { s3_path, uploadId, parts: partsMetadata, type: 'multipart' };
  }

  // CASE 2: SINGLE PUT UPLOAD (Fallback - may fail on 2GB depending on S3 config)
  if (presigned_url) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('PUT', presigned_url);
      xhr.setRequestHeader('Content-Type', file.type);

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) {
          const percent = Math.round((event.loaded / event.total) * 100);
          onProgress(percent);
        }
      };

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve({ s3_path, type: 'single' });
        } else {
          reject(new Error(`Upload failed with status ${xhr.status}`));
        }
      };

      xhr.onerror = () => reject(new Error('Network error during upload.'));
      xhr.send(file); // Passing the file object directly streams it from disk
    });
  }

  throw new Error('Invalid presigned data received from server.');
};

export const validate_video_file = (file) => {
  const max_size = 2 * 1024 * 1024 * 1024; // 2GB
  const allowed_types = ['video/mp4', 'video/webm', 'video/quicktime', 'video/x-matroska'];

  if (!file) return { valid: false, error: 'No file selected' };
  if (file.size > max_size) return { valid: false, error: 'File exceeds 2GB limit' };
  if (!allowed_types.includes(file.type)) {
    return { valid: false, error: 'Invalid format. Use MP4, MOV, or WebM' };
  }

  return { valid: true };
};