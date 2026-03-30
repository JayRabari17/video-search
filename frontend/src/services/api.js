import axios from 'axios';
import runtimeConfig from '../config/runtimeConfig.js';
import { getAccessToken } from '../auth/loginSession.js';

/**
 * API Service for Video Search Application
 * 
 * IMPORTANT: Backend URL Configuration
 * =====================================
 * This service uses the backend URL from the CloudFormation stack's ApiCloudFrontURL output.
 * The URL is loaded dynamically at runtime from /config.json, which is generated during deployment.
 * 
 * Deployment Flow:
 * 1. CloudFormation stack deploys backend infrastructure
 * 2. Stack outputs ApiCloudFrontURL (e.g., https://d1234567890.cloudfront.net)
 * 3. deploy-frontend.sh extracts this URL from stack outputs
 * 4. config.json is generated with the extracted URL
 * 5. config.json is uploaded to S3 with no-cache headers
 * 6. Frontend loads config.json at runtime via runtimeConfig.js
 * 7. All API calls use the dynamically loaded backend URL
 * 
 * DO NOT hardcode backend URLs in this file!
 * See frontend/BACKEND_URL_CONFIG.md for detailed documentation.
 */

// Legacy axios instance - kept for backward compatibility if needed
// Note: Most functions now use fetch with dynamic URLs from runtimeConfig
const api = axios.create({
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Helper function to get backend URL from runtime configuration
 * Ensures configuration is loaded before making API calls
 * @returns {Promise<string>} Backend URL
 */
const getBackendUrl = async () => {
  try {
    await runtimeConfig.load();
    return runtimeConfig.getBackendUrl();
  } catch (error) {
    console.error('❌ Failed to load configuration:', error.message);
    throw new Error(`Configuration error: ${error.message}`);
  }
};

const getAuthHeaders = () => {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
};

// Old searchClips - commented out
// export const searchClips = async (query, topK = 10) => {
//   try {
//     const response = await api.post('/hybrid-search', {
//       query,
//       top_k: topK,
//     });
//     return response.data;
//   } catch (error) {
//     console.error('Error searching clips:', error);
//     throw error;
//   }
// };

// Helper function to convert file to base64
const fileToBase64 = (file) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const base64String = reader.result.split(',')[1]; // Extract base64 part only
      resolve(base64String);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
};

// Unified search function - handles both text and image searches
export const searchClips = async (query, topK = 10, searchType = 'vector', imageFile = null) => {
  try {
    // Load config first
    const backendUrl = await getBackendUrl();

    // Validate that at least one input is provided
    // Entity-only search is valid (no text, no image) as long as entityId is provided.
    if (!query && !imageFile && !entityId) {
      throw new Error('Either query text, image file, or entity is required');
    }

    let requestBody = {
      top_k: topK,
      search_type: searchType
    };

    // Handle text search
    if (query) {
      console.log('🔍 Starting text search:', {
        query,
        topK,
        searchType
      });
      requestBody.query_text = query;
    }

    // Handle image search
    if (imageFile) {
      console.log('📷 Starting image search with file:', {
        name: imageFile.name,
        type: imageFile.type,
        size: `${(imageFile.size / 1024).toFixed(2)}KB`,
        topK
      });

      // Validate file type
      const validImageTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
      if (!validImageTypes.includes(imageFile.type)) {
        throw new Error(`Invalid image type: ${imageFile.type}. Supported types: JPEG, PNG, GIF, WebP`);
      }

      // Validate file size (max 5MB)
      const maxSize = 5 * 1024 * 1024;
      if (imageFile.size > maxSize) {
        throw new Error(`Image file exceeds 5MB limit. Size: ${(imageFile.size / 1024 / 1024).toFixed(2)}MB`);
      }

      console.log('✓ File validation passed');
      console.log('🔄 Converting image to base64...');

      const base64String = await fileToBase64(imageFile);
      console.log(`✓ Base64 conversion complete. Length: ${base64String.length} characters`);

      requestBody.image_base64 = base64String;
    }

    const response = await fetch(`${backendUrl}/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify(requestBody),
    });

    // Check if response is ok
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(`API returned status code: ${response.status}. ${errorData.detail || ''}`);
    }

    // Parse the response body
    const data = await response.json();
    console.log('✓ Search completed successfully');
    console.log(`  - Results found: ${data.clips?.length || 0}`);
    console.log(`  - Total: ${data.total}`);

    return data;
  } catch (error) {
    console.error('❌ Error searching clips:', error);
    throw error;
  }
};

// Legacy wrapper for image search - calls unified searchClips function
export const searchClipsWithImage = async (imageFile, topK = 10, searchType = 'vector') => {
  return searchClips(null, topK, searchType, imageFile);
};

// ============ MARENGO 3 SEARCH FUNCTIONS ============

// Unified search function for Marengo 3 - handles text, image, or combined text+image searches
// Supported search types: 'vector', 'visual', 'audio', 'transcription'
export const searchClipsMarengo3 = async (
  query = null,
  topK = 10,
  searchType = 'vector',
  imageFile = null,
  categories = null,
  minRelevance = null,
  maxSegmentsPerVideo = null,
  entityId = null
) => {
  try {
    // Load config first
    const backendUrl = await getBackendUrl();

    // Validate that at least one input is provided
    // Entity-only search is valid (no text, no image) as long as entityId is provided.
    if (!query && !imageFile && !entityId) {
      throw new Error('Either query text, image file, or entity is required');
    }

    // Validate search type
    const validSearchTypes = ['vector', 'visual', 'audio', 'transcription', 'visual_audio', 'audio_transcription', 'visual_transcription'];
    if (!validSearchTypes.includes(searchType)) {
      throw new Error(`Invalid search type: ${searchType}. Supported types: ${validSearchTypes.join(', ')}`);
    }

    let requestBody = {
      top_k: topK,
      search_type: searchType
    };

    // Add optional filter params
    if (categories && categories.length > 0) {
      requestBody.categories = categories;
    }
    if (minRelevance !== null && minRelevance !== undefined) {
      requestBody.min_relevance = minRelevance;
    }
    if (maxSegmentsPerVideo !== null && maxSegmentsPerVideo !== undefined) {
      requestBody.max_segments_per_video = maxSegmentsPerVideo;
    }

    if (entityId) {
      requestBody.entity_id = entityId;
    }

    // Determine search type for logging
    let searchInputType = '';
    if (query && imageFile) {
      searchInputType = 'multimodal (text + image)';
      console.log('🔄 Starting multimodal search (Marengo 3):', {
        query,
        imageFile: imageFile.name,
        topK,
        searchType
      });
    } else if (imageFile) {
      searchInputType = 'image-only';
      console.log('📷 Starting image-only search (Marengo 3) with file:', {
        name: imageFile.name,
        type: imageFile.type,
        size: `${(imageFile.size / 1024).toFixed(2)}KB`,
        topK,
        searchType
      });
    } else {
      searchInputType = 'text-only';
      console.log('🔍 Starting text-only search (Marengo 3):', {
        query,
        topK,
        searchType
      });
    }

    // Handle text search
    if (query) {
      requestBody.query_text = query;
    }

    // Handle image search
    if (imageFile) {
      // Validate file type
      const validImageTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
      if (!validImageTypes.includes(imageFile.type)) {
        throw new Error(`Invalid image type: ${imageFile.type}. Supported types: JPEG, PNG, GIF, WebP`);
      }

      // Validate file size (max 5MB)
      const maxSize = 5 * 1024 * 1024;
      if (imageFile.size > maxSize) {
        throw new Error(`Image file exceeds 5MB limit. Size: ${(imageFile.size / 1024 / 1024).toFixed(2)}MB`);
      }

      console.log('✓ File validation passed');
      console.log('🔄 Converting image to base64...');

      const base64String = await fileToBase64(imageFile);
      console.log(`✓ Base64 conversion complete. Length: ${base64String.length} characters`);

      requestBody.image_base64 = base64String;
    }

    console.log(`📤 Sending ${searchInputType} request to /search-3 (searchType: ${searchType})`);
    const response = await fetch(`${backendUrl}/search-3`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify(requestBody),
    });

    // Check if response is ok
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(`API returned status code: ${response.status}. ${errorData.detail || ''}`);
    }

    // Parse the response body
    const data = await response.json();
    console.log('✓ Search (Marengo 3) completed successfully');
    console.log(`  - Search input type: ${searchInputType}`);
    console.log(`  - Search type: ${searchType}`);
    console.log(`  - Results found: ${data.clips?.length || 0}`);
    console.log(`  - Total: ${data.total}`);
    console.log(`  - Search Intent: ${data.classified_intent}`);
    console.log(`  - Weights used: ${data.weights_used}`);

    return data;
  } catch (error) {
    console.error('❌ Error searching clips (Marengo 3):', error);
    throw error;
  }
};

// ============ ENTITY APIs ============

export const listEntities = async () => {
  const backendUrl = await getBackendUrl();
  const response = await fetch(`${backendUrl}/entities`, {
    headers: {
      ...getAuthHeaders(),
    },
  });
  if (!response.ok) {
    throw new Error('Failed to load entities');
  }
  return await response.json();
};

export const createEntity = async (name, imageKeys, primaryImageKey) => {
  const backendUrl = await getBackendUrl();
  const body = {
    name,
    image_keys: imageKeys,
    primary_image_key: primaryImageKey,
  };
  const response = await fetch(`${backendUrl}/entities`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to create entity');
  }
  return await response.json();
};

// Wrapper for Marengo 3 image-only search
export const searchClipsWithImageMarengo3 = async (imageFile, topK = 10, searchType = 'vector') => {
  return searchClipsMarengo3(null, topK, searchType, imageFile);
};

// Wrapper for Marengo 3 text-only search
export const searchClipsTextMarengo3 = async (query, topK = 10, searchType = 'vector') => {
  return searchClipsMarengo3(query, topK, searchType, null);
};

// Individual search type wrappers for Marengo 3
export const searchClipsVisualMarengo3 = async (query, topK = 10, imageFile = null) => {
  return searchClipsMarengo3(query, topK, 'visual', imageFile);
};

export const searchClipsAudioMarengo3 = async (query, topK = 10, imageFile = null) => {
  return searchClipsMarengo3(query, topK, 'audio', imageFile);
};

export const searchClipsTranscriptionMarengo3 = async (query, topK = 10, imageFile = null) => {
  return searchClipsMarengo3(query, topK, 'transcription', imageFile);
};

// # COMMENTED OUT: Vector search type combinations replaced by intent classification
// # Frontend now only sends: 'vector', 'visual', 'audio', 'transcription'
// # Backend uses intent classification when 'vector' is received
// export const searchClipsVectorVisualAudioMarengo3 = async (query, topK = 10, imageFile = null) => {
//   return searchClipsMarengo3(query, topK, 'vector_visual_audio', imageFile);
// };
//
// export const searchClipsVectorVisualTranscriptionMarengo3 = async (query, topK = 10, imageFile = null) => {
//   return searchClipsMarengo3(query, topK, 'vector_visual_transcription', imageFile);
// };
//
// export const searchClipsVectorAudioTranscriptionMarengo3 = async (query, topK = 10, imageFile = null) => {
//   return searchClipsMarengo3(query, topK, 'vector_audio_transcription', imageFile);
// };


export const listAllVideos = async () => {
  try {
    // Load config first
    const backendUrl = await getBackendUrl();

    const response = await fetch(`${backendUrl}/list`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      }
    });
    let data = await response.json();
    console.log(data)
    return data;
  } catch (error) {
    console.error('Error listing videos:', error);
    throw error;
  }
};

export const getPresignedUploadUrl = async (filename, fileSize, category, contentType) => {
  try {
    // Load config first
    const backendUrl = await getBackendUrl();

    // Build query params
    let queryParams = `filename=${encodeURIComponent(filename)}`;
    if (fileSize) {
      queryParams += `&file_size=${fileSize}`;
    }
    if (category) {
      queryParams += `&category=${encodeURIComponent(category)}`;
    }
    if (contentType) {
      queryParams += `&content_type=${encodeURIComponent(contentType)}`;
    }

    const response = await fetch(`${backendUrl}/generate-upload-presigned-url?${queryParams}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      }
    });

    if (!response.ok) {
      throw new Error(`Failed to generate presigned URL: ${response.status}`);
    }

    const data = await response.json();

    if (data.type === 'multipart') {
      console.log('✓ Multipart upload initialized:', {
        s3_key: data.s3_key,
        uploadId: data.uploadId,
        parts_count: data.presigned_urls?.length || 0,
        chunk_size: data.chunk_size,
        expires_in: data.expires_in
      });
    } else {
      console.log('✓ Single upload URL generated:', {
        s3_key: data.s3_key,
        expires_in: data.expires_in
      });
    }

    return data;
  } catch (error) {
    console.error('❌ Error getting presigned upload URL:', error);
    throw error;
  }
};

export const completeMultipartUpload = async (uploadData) => {
  try {
    // Load config first
    const backendUrl = await getBackendUrl();

    const { uploadId, s3_key, parts } = uploadData;

    if (!uploadId || !s3_key || !parts) {
      throw new Error('Missing required fields: uploadId, s3_key, parts');
    }

    console.log('🔄 Completing multipart upload:', {
      uploadId,
      s3_key,
      parts_count: parts.length
    });

    const response = await fetch(`${backendUrl}/complete-multipart-upload`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify({
        uploadId,
        s3_key,
        parts
      })
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(`Failed to complete multipart upload: ${response.status} - ${errorData.detail || ''}`);
    }

    const data = await response.json();
    console.log('✓ Multipart upload completed successfully:', {
      s3_path: data.s3_path,
      message: data.message
    });

    return data;
  } catch (error) {
    console.error('❌ Error completing multipart upload:', error);
    throw error;
  }
};

export default api;
