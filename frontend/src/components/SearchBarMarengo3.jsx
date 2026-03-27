import React, { useState, useEffect, useRef } from 'react';
import { Search, X, Loader2, ChevronDown, ImagePlus as ImageIcon, ArrowRight, Tag, Square, CheckSquare } from 'lucide-react';

const CATEGORIES = ['Tutorial', 'Entertainment', 'Documentary', 'News', 'Sports', 'Music', 'Education', 'Lifestyle', 'Gaming'];

const SearchBarMarengo3 = ({ onSearch, isLoading, onSearchTypeChange, queryValue = '', onQueryChange }) => {
  const [query, setQuery] = useState(queryValue);
  const [selectedImage, setSelectedImage] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [imageError, setImageError] = useState(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    setQuery(queryValue || '');
  }, [queryValue]);

  const updateQuery = (value) => {
    setQuery(value);
    onQueryChange?.(value);
  };

  const [showDropdown, setShowDropdown] = useState(false);
  const [showCategoryDropdown, setShowCategoryDropdown] = useState(false);
  const [visual, setVisual] = useState(true);
  const [audio, setAudio] = useState(true);
  const [transcription, setTranscription] = useState(false);
  const [topK, setTopK] = useState(10);
  const [selectedCategories, setSelectedCategories] = useState([]);
  const [minRelevance, setMinRelevance] = useState(null);
  const [maxSegmentsPerVideo, setMaxSegmentsPerVideo] = useState(null);
  const dropdownRef = useRef(null);
  const categoryDropdownRef = useRef(null);

  // Determine search type based on selections
  const getSearchType = () => {
    // Single modality selections
    if (visual && !audio && !transcription) return 'visual';
    if (!visual && audio && !transcription) return 'audio';
    // if (!visual && !audio && transcription) return 'transcription';

    // UPDATED: 7 search options - specific combinations instead of intent-based
    // Two-modality combinations
    if (visual && audio && !transcription) return 'vector';
    // if (visual && !audio && transcription) return 'visual_transcription';
    // if (!visual && audio && transcription) return 'audio_transcription';

    // All three modalities → 'vector' (balanced search)
    if (visual && audio && transcription) return 'vector';

    // COMMENTED OUT: Old intent-based logic
    // // Any combination (including all three) → 'vector'
    // // Backend will use intent classification to determine modality focus
    // return 'vector'; // default for any multi-modality combination

    // Default fallback (if none selected, use vector)
    return 'vector';
  };

  const handle_submit = async (e) => {
    e.preventDefault();

    const searchType = getSearchType();

    // Support combined text + image search
    if (query.trim() || selectedImage) {
      console.log("Searching (Marengo 3):", {
        hasText: !!query.trim(),
        hasImage: !!selectedImage,
        searchType,
        topK,
        categories: selectedCategories,
        minRelevance,
        maxSegmentsPerVideo
      });
      // Pass both query and image file to parent, plus filter params
      onSearch(
        query.trim() || null,
        searchType,
        topK,
        null,
        selectedImage,
        selectedCategories.length > 0 ? selectedCategories : null,
        minRelevance,
        maxSegmentsPerVideo
      );
    }
  };

  const clear_query = () => {
    updateQuery('');
  };

  const handleImageSelect = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Clear previous errors
    setImageError(null);

    // Validate file type
    const validImageTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
    if (!validImageTypes.includes(file.type)) {
      setImageError(`Invalid image type: ${file.type}. Supported: JPEG, PNG, GIF, WebP`);
      return;
    }

    // Validate file size (5MB limit)
    const maxSize = 5 * 1024 * 1024;
    if (file.size > maxSize) {
      setImageError(`Image exceeds 5MB limit. Size: ${(file.size / 1024 / 1024).toFixed(2)}MB`);
      return;
    }

    // Set selected image - DO NOT clear text query
    setSelectedImage(file);

    // Create preview
    const reader = new FileReader();
    reader.onload = (event) => {
      setImagePreview(event.target?.result);
    };
    reader.readAsDataURL(file);
  };

  const removeImage = () => {
    setSelectedImage(null);
    setImagePreview(null);
    setImageError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleVisualChange = (e) => {
    const newVisual = e.target.checked;
    setVisual(newVisual);
    onSearchTypeChange?.(getSearchType());
  };

  const handleAudioChange = (e) => {
    const newAudio = e.target.checked;
    setAudio(newAudio);
    onSearchTypeChange?.(getSearchType());
  };

  const handleTranscriptionChange = (e) => {
    const newTranscription = e.target.checked;
    setTranscription(newTranscription);
    onSearchTypeChange?.(getSearchType());
  };

  const toggleCategory = (cat) => {
    setSelectedCategories((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
    );
  };

  const selectAllCategories = () => setSelectedCategories([...CATEGORIES]);
  const clearAllCategories = () => setSelectedCategories([]);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setShowDropdown(false);
      }
      if (categoryDropdownRef.current && !categoryDropdownRef.current.contains(e.target)) {
        setShowCategoryDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <form onSubmit={handle_submit} className="w-full">
      {/* Main Row - Search bar takes more space */}
      <div className="flex flex-col sm:flex-row gap-3 sm:items-center">
        {/* Main Search Container - Larger and more prominent */}
        <div className="relative flex-1 min-w-0">
          {/* Search Input */}
          <div className={`relative transition-all duration-300 ${selectedImage ? 'min-h-32 p-4' : 'h-16'
            } rounded-3xl border border-gray-200 bg-white shadow-sm hover:shadow-md flex flex-col`}>

            {/* Image Preview - Show alongside text input */}
            {imagePreview && (
              <div className="flex gap-3 mb-2 items-center">
                {/* Image Thumbnail */}
                <div className="relative flex-shrink-0 rounded-lg overflow-hidden bg-gray-100 w-24 h-24 flex items-center justify-center">
                  <img
                    src={imagePreview}
                    alt="Selected"
                    className="max-w-full max-h-full object-contain"
                  />
                  {/* Remove button - top right */}
                  <button
                    type="button"
                    onClick={removeImage}
                    className="absolute top-1 right-1 bg-red-500 hover:bg-red-600 text-white rounded-full p-1 transition-colors shadow-md"
                    title="Remove image"
                  >
                    <X size={14} />
                  </button>
                </div>

              </div>
            )}

            {/* Text Input - Always visible */}
            <div className="relative w-full h-full flex items-center px-2">
              <div className="absolute left-11 text-gray-400 flex-shrink-0">
                <Search size={22} />
              </div>
              <input
                type="text"
                value={query}
                onChange={(e) => updateQuery(e.target.value)}
                placeholder={selectedImage ? "Add text to refine search..." : "Search videos, actions, or objects..."}
                className="w-full h-full pl-16 pr-20 text-base sm:text-lg bg-transparent focus:outline-none"
                disabled={isLoading}
              />

              {/* Image Upload Button */}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className={`absolute left-2 flex items-center justify-center w-8 h-8 rounded-lg transition-colors ${selectedImage
                  ? 'bg-green-200 hover:bg-green-300 text-green-600'
                  : 'bg-gray-200 hover:bg-gray-300 text-gray-600'
                  }`}
                disabled={isLoading}
                title={selectedImage ? "Change image" : "Upload image to search"}
              >
                <ImageIcon size={16} />
              </button>

              {query && !isLoading && (
                <button
                  type="button"
                  onClick={clear_query}
                  className="absolute right-6 text-gray-400 hover:text-gray-600 transition-colors"
                >
                  <X size={20} />
                </button>
              )}

              {isLoading && (
                <div className="absolute right-6">
                  <Loader2 size={20} className="animate-spin text-gray-600" />
                </div>
              )}
            </div>
          </div>

          {/* Error message - Outside search bar */}
          {imageError && (
            <div className="mt-2 p-3 bg-red-50 border border-red-200 rounded-xl">
              <p className="text-red-600 text-sm">{imageError}</p>
            </div>
          )}

          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/gif,image/webp"
            onChange={handleImageSelect}
            className="hidden"
          />
        </div>

        {/* Submit Button */}
        <button
          type="submit"
          disabled={isLoading || (!query.trim() && !selectedImage)}
          className="flex items-center justify-center w-full sm:w-14 h-14 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white rounded-2xl transition-colors shadow-sm hover:shadow-md disabled:cursor-not-allowed flex-shrink-0"
          title="Search"
        >
          {isLoading ? (
            <Loader2 size={20} className="animate-spin" />
          ) : (
            <ArrowRight size={20} />
          )}
        </button>

        {/* Categories Dropdown */}
        <div ref={categoryDropdownRef} className="relative flex-shrink-0 w-full sm:w-auto">
          <button
            type="button"
            onClick={() => setShowCategoryDropdown(!showCategoryDropdown)}
            className={`flex items-center justify-center gap-1 w-full sm:w-auto px-3 py-4 bg-gray-100 hover:bg-gray-200 text-gray-600 rounded-2xl border transition-colors ${selectedCategories.length > 0
              ? 'border-blue-400 bg-blue-50 text-blue-700'
              : 'border-gray-200'
              }`}
            disabled={isLoading}
            title="Filter by category"
          >
            <Tag size={18} />
            <span className="text-sm font-medium whitespace-nowrap">
              {selectedCategories.length > 0
                ? `${selectedCategories.length}`
                : ''}
            </span>
            <ChevronDown size={18} />
          </button>

          {/* Category Dropdown Menu */}
          {showCategoryDropdown && (
            <div className="absolute right-0 top-full mt-2 w-64 bg-white rounded-2xl border border-gray-100 shadow-2xl p-3 z-50 max-h-[70vh] overflow-y-auto">
              <div className="mb-1">
                <div className="flex items-center justify-between px-2 mb-2">
                  <span className="text-xs font-bold uppercase tracking-wide text-gray-500">Categories</span>
                  <div className="flex gap-2">
                    <button type="button" onClick={selectAllCategories} className="text-xs text-blue-500 hover:text-blue-700 font-medium px-2 py-1 rounded hover:bg-blue-50 transition-colors">All</button>
                    <button type="button" onClick={clearAllCategories} className="text-xs text-red-500 hover:text-red-700 font-medium px-2 py-1 rounded hover:bg-red-50 transition-colors">Clear</button>
                  </div>
                </div>
                <div className="flex flex-col gap-0.5">
                  {CATEGORIES.map((cat) => (
                    <button
                      key={cat}
                      type="button"
                      onClick={() => toggleCategory(cat)}
                      className="flex items-center justify-between px-4 py-2 hover:bg-gray-50 rounded-lg text-left transition-colors"
                    >
                      <span className="text-sm text-gray-700 font-medium">{cat}</span>
                      {selectedCategories.includes(cat) ? (
                        <div className="w-5 h-5 bg-blue-500 rounded flex items-center justify-center">
                          <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" /></svg>
                        </div>
                      ) : (
                        <div className="w-5 h-5 border-2 border-gray-300 rounded" />
                      )}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Options Button - Relative for dropdown positioning */}
        <div ref={dropdownRef} className="relative flex-shrink-0 w-full sm:w-auto">
          <button
            type="button"
            onClick={() => setShowDropdown(!showDropdown)}
            className={`flex items-center justify-center gap-2 w-full sm:w-auto px-3 py-4 bg-gray-100 hover:bg-gray-200 text-gray-600 rounded-2xl border transition-colors ${(minRelevance !== null || maxSegmentsPerVideo !== null)
              ? 'border-blue-400 bg-blue-50'
              : 'border-gray-200'
              }`}
            disabled={isLoading}
            title="Search options"
          >
            <div className="w-5 h-5 flex items-center justify-center flex-shrink-0">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
              </svg>
            </div>
            <ChevronDown size={18} />
          </button>

          {/* Dropdown Menu - Positioned below options button */}
          {showDropdown && (
            <div className="absolute right-0 top-full mt-2 w-72 bg-white rounded-2xl border border-gray-100 shadow-2xl p-3 z-50 max-h-[70vh] overflow-y-auto">
              {/* Modality Section */}
              <div className="mb-3">
                <span className="text-xs font-bold uppercase tracking-wide text-gray-500 px-2">Modalities</span>
                <div className="flex flex-col gap-1 mt-1">
                  {/* Visual Checkbox */}
                  <label className="flex items-center justify-between cursor-pointer hover:bg-gray-50 px-4 py-2.5 rounded-xl transition-colors group">
                    <span className="text-sm font-medium text-gray-600 group-hover:text-gray-900">Visual</span>
                    <div className={`w-5 h-5 rounded-md border flex items-center justify-center transition-colors ${visual ? 'bg-blue-600 border-blue-600' : 'border-gray-300 bg-white'}`}>
                      {visual && <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" /></svg>}
                    </div>
                    <input type="checkbox" checked={visual} onChange={handleVisualChange} className="hidden" />
                  </label>
                  {/* Audio Checkbox */}
                  <label className="flex items-center justify-between cursor-pointer hover:bg-gray-50 px-4 py-2.5 rounded-xl transition-colors group">
                    <span className="text-sm font-medium text-gray-600 group-hover:text-gray-900">Audio</span>
                    <div className={`w-5 h-5 rounded-md border flex items-center justify-center transition-colors ${audio ? 'bg-blue-600 border-blue-600' : 'border-gray-300 bg-white'}`}>
                      {audio && <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" /></svg>}
                    </div>
                    <input type="checkbox" checked={audio} onChange={handleAudioChange} className="hidden" />
                  </label>
                </div>
              </div>

              {/* Divider */}
              <div className="border-t border-gray-100 my-2" />

              {/* Min Relevance */}
              <div className="mb-3 px-2">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-bold uppercase tracking-wide text-gray-500">Min Relevance</span>
                  <span className="text-xs font-semibold text-gray-700">
                    {minRelevance !== null ? `${Math.round(minRelevance * 100)}%` : 'Off'}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    value={minRelevance !== null ? minRelevance : 0}
                    onChange={(e) => {
                      const val = parseFloat(e.target.value);
                      setMinRelevance(val === 0 ? null : val);
                    }}
                    className="flex-1 h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                  />
                  {minRelevance !== null && (
                    <button
                      type="button"
                      onClick={() => setMinRelevance(null)}
                      className="text-xs text-gray-400 hover:text-gray-600"
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
              </div>

              {/* Max Segments Per Video */}
              <div className="px-2">
                <span className="text-xs font-bold uppercase tracking-wide text-gray-500">Max Segments / Video</span>
                <div className="flex items-center gap-2 mt-1">
                  <input
                    type="number"
                    min="1"
                    max="50"
                    placeholder="No limit"
                    value={maxSegmentsPerVideo !== null ? maxSegmentsPerVideo : ''}
                    onChange={(e) => {
                      const val = e.target.value ? parseInt(e.target.value, 10) : null;
                      setMaxSegmentsPerVideo(val && val > 0 ? val : null);
                    }}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-xl bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-400/30"
                  />
                  {maxSegmentsPerVideo !== null && (
                    <button
                      type="button"
                      onClick={() => setMaxSegmentsPerVideo(null)}
                      className="text-xs text-gray-400 hover:text-gray-600"
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </form>
  );
};

export default SearchBarMarengo3;
