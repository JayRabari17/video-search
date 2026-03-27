import React, { useState, useRef, useEffect } from 'react';
import { Upload, CheckCircle, AlertCircle, FileVideo, Tag, ChevronDown, ChevronUp, Square, CheckSquare } from 'lucide-react';
import { motion } from 'framer-motion';
import { upload_to_s3, validate_video_file } from '../utils/s3Upload';
import { getPresignedUploadUrl, completeMultipartUpload } from '../services/api';

const CATEGORIES = ['Tutorial', 'Entertainment', 'Documentary', 'News', 'Sports', 'Music', 'Education', 'Lifestyle', 'Gaming'];

const VideoUpload = () => {
  const [file, setFile] = useState(null);
  const [selectedCategories, setSelectedCategories] = useState([]);
  const [categoryDropdownOpen, setCategoryDropdownOpen] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStatus, setUploadStatus] = useState('idle'); // idle, uploading, completed, error
  const [s3Url, setS3Url] = useState('');
  const [error, setError] = useState('');
  const categoryDropdownRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (categoryDropdownRef.current && !categoryDropdownRef.current.contains(e.target)) {
        setCategoryDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);


  const handle_file_select = (e) => {
    const selected_file = e.target.files[0];
    if (selected_file) {
      const validation = validate_video_file(selected_file);
      if (!validation.valid) {
        setError(validation.error);
        setFile(null);
        return;
      }
      setFile(selected_file);
      setError('');
      setUploadStatus('idle');
    }
  };

  const toggleCategory = (cat) => {
    setSelectedCategories((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
    );
  };

  const selectAllCategories = () => {
    setSelectedCategories([...CATEGORIES]);
  };

  const clearAllCategories = () => {
    setSelectedCategories([]);
  };

  const handle_upload = async () => {
    if (!file || selectedCategories.length === 0) return;

    try {
      setUploadStatus('uploading');
      setError('');
      setUploadProgress(0);

      const categoryParam = selectedCategories.join(',');
      console.log('Requesting presigned URL for:', file.name, 'categories:', categoryParam);

      // 1. Get URLs (Backend should detect large files and return multipart info)
      const presignedData = await getPresignedUploadUrl(file.name, file.size, categoryParam);

      console.log(presignedData);

      // 2. Perform the upload
      const result = await upload_to_s3(file, presignedData, (progress) => {
        console.log(`Upload progress: ${progress}%`);
        setUploadProgress(progress);
      });

      // 3. If Multipart, notify backend to merge parts
      if (result.type === 'multipart') {
        await completeMultipartUpload({
          uploadId: result.uploadId,
          parts: result.parts,
          fileName: file.name
        });
      }

      setS3Url(result.s3_path);
      console.log('✓ Video uploaded to S3:', result.s3_path);
      setUploadStatus('completed');

    } catch (err) {
      console.error('Upload error:', err);
      setError(err.message || 'Failed to upload video');
      setUploadStatus('error');
    }
  };

  const reset_form = () => {
    setFile(null);
    setSelectedCategories([]);
    setUploadStatus('idle');
    setS3Url('');
    setError('');
  };

  return (
    <motion.section
      initial={{ opacity: 0, y: 50 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -50 }}
      transition={{ duration: 0.7 }}
      className="w-full h-full flex flex-col items-center justify-center px-4"
    >
      {/* Header */}
      <div className="text-center mb-8">
        <h2 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold mb-4 bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">
          Share Your Story
        </h2>
        <p className="text-blue-600 mb-8 max-w-xl text-center">
          Upload your best moments. Smooth, fast, and secure.
        </p>
      </div>

      {/* Upload Card */}
      <div className="bg-white rounded-2xl shadow-lg border border-gray-200 p-4 sm:p-6 lg:p-8 w-full max-w-3xl">
        {uploadStatus === 'idle' || uploadStatus === 'error' ? (
          <>
            {/* File Input */}
            <div className="mb-6">
              <label
                htmlFor="video-upload"
                className="block w-full cursor-pointer"
              >
                <div className="border-2 border-dashed border-blue-300 rounded-xl p-8 sm:p-12 lg:p-16 text-center hover:border-blue-500 hover:bg-blue-50 transition-all duration-200 min-h-[220px] sm:min-h-[280px] flex flex-col items-center justify-center">
                  <FileVideo size={56} className="mx-auto text-blue-400 mb-4 sm:mb-6" />
                  <p className="text-lg sm:text-xl font-semibold text-gray-700 mb-3 break-words">
                    {file ? file.name : 'Click to select video'}
                  </p>
                  <p className="text-sm sm:text-base text-gray-500">
                    Acceptable format: MP4, MOV, WebM
                    <br />
                    Maximum file size: 2GB
                  </p>
                </div>
                <input
                  id="video-upload"
                  type="file"
                  accept="video/mp4,video/webm,video/quicktime"
                  onChange={handle_file_select}
                  className="hidden"
                />
              </label>
            </div>

            {/* File Info */}
            {file && (
              <div className="mb-6 p-4 bg-gray-50 rounded-lg">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-gray-900">{file.name}</p>
                    <p className="text-sm text-gray-500">
                      {(file.size / (1024 * 1024)).toFixed(2)} MB
                    </p>
                  </div>
                  <CheckCircle className="text-green-500" size={24} />
                </div>
              </div>
            )}

            {/* Category Dropdown */}
            <div ref={categoryDropdownRef} className="mb-6 relative">
              <button
                type="button"
                onClick={() => setCategoryDropdownOpen((o) => !o)}
                className={`w-full flex items-center gap-3 px-4 py-3.5 bg-gray-100 border border-gray-200 rounded-xl shadow-sm text-left transition-all hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-400/30 ${selectedCategories.length === 0 ? 'text-gray-500' : 'text-gray-900'
                  } ${categoryDropdownOpen ? 'ring-2 ring-blue-400/30' : ''}`}
              >
                <Tag className="flex-shrink-0 text-gray-400" size={20} />
                <span className="flex-1">
                  {selectedCategories.length > 0
                    ? selectedCategories.join(', ')
                    : 'Select at least one category (required)'}
                </span>
                {categoryDropdownOpen ? (
                  <ChevronUp className="flex-shrink-0 text-gray-400" size={20} />
                ) : (
                  <ChevronDown className="flex-shrink-0 text-gray-400" size={20} />
                )}
              </button>
              {categoryDropdownOpen && (
                <div className="absolute top-full left-0 right-0 mt-1.5 bg-white rounded-xl shadow-lg border border-gray-200 py-2 z-50 max-h-64 overflow-y-auto">
                  <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100">
                    <span className="text-xs font-bold uppercase tracking-wide text-gray-600">
                      CATEGORIES
                    </span>
                    <div className="flex gap-4">
                      <button
                        type="button"
                        onClick={selectAllCategories}
                        className="text-sm text-sky-500 hover:text-sky-600 font-medium"
                      >
                        All
                      </button>
                      <button
                        type="button"
                        onClick={clearAllCategories}
                        className="text-sm text-sky-500 hover:text-sky-600 font-medium"
                      >
                        Clear
                      </button>
                    </div>
                  </div>
                  <div className="py-1">
                    {CATEGORIES.map((cat) => (
                      <button
                        key={cat}
                        type="button"
                        onClick={() => toggleCategory(cat)}
                        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-gray-50 text-left"
                      >
                        <span className="text-gray-800">{cat}</span>
                        {selectedCategories.includes(cat) ? (
                          <CheckSquare className="text-sky-500" size={20} />
                        ) : (
                          <Square className="text-gray-300" size={20} />
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Error Message */}
            {error && (
              <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
                <AlertCircle className="text-red-500 flex-shrink-0 mt-0.5" size={20} />
                <div>
                  <p className="text-red-700 font-medium">Error</p>
                  <p className="text-red-600 text-sm">{error}</p>
                </div>
              </div>
            )}

            {/* Upload Button */}
            <button
              onClick={handle_upload}
              disabled={!file || selectedCategories.length === 0}
              className="w-full flex items-center justify-center gap-3 px-6 sm:px-8 py-4 sm:py-5 bg-gradient-to-r from-blue-600 to-blue-500 text-white rounded-xl font-semibold text-base sm:text-lg shadow-lg hover:shadow-xl hover:scale-[1.02] active:scale-[0.99] transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
            >
              <Upload size={24} />
              Upload Video to S3
            </button>
          </>
        ) : (
          <>
            {/* Upload Progress */}
            {uploadStatus === 'uploading' && (
              <div className="space-y-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-gray-700 font-medium">Uploading to S3...</span>
                  <span className="text-primary-600 font-semibold">{uploadProgress}%</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
                  <div
                    className="bg-gradient-to-r from-primary-600 to-primary-400 h-full transition-all duration-300 rounded-full"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
                <p className="text-sm text-gray-500 text-center">
                  Please wait while we upload your video...
                </p>
              </div>
            )}

            {/* Completion */}
            {uploadStatus === 'completed' && (
              <div className="text-center space-y-4">
                <div className="inline-flex items-center justify-center w-20 h-20 bg-green-100 rounded-full mb-4">
                  <CheckCircle size={48} className="text-green-600" />
                </div>
                <h3 className="text-2xl font-bold text-gray-900">
                  Video Uploaded Successfully!
                </h3>
                <p className="text-gray-600">
                  Your video has been uploaded to S3.
                </p>
                <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                  <p className="text-sm text-blue-700 break-all">
                    <strong>S3 Path:</strong> {s3Url}
                  </p>
                </div>
                <div className="pt-4 space-y-3">
                  <button
                    onClick={reset_form}
                    className="w-full px-6 py-3 bg-gradient-to-r from-blue-600 to-blue-500 text-white rounded-xl font-semibold hover:shadow-lg transition-all"
                  >
                    Upload Another Video
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </motion.section>
  );
};

export default VideoUpload;