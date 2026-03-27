import React, { useState, useEffect } from 'react';
import { Search, X, Loader2, ChevronDown } from 'lucide-react';

const SearchBar = ({ onSearch, isLoading, onSearchTypeChange, queryValue = '', onQueryChange }) => {
  const [query, setQuery] = useState(queryValue);

  useEffect(() => {
    setQuery(queryValue || '');
  }, [queryValue]);

  const updateQuery = (value) => {
    setQuery(value);
    onQueryChange?.(value);
  };

  const [showDropdown, setShowDropdown] = useState(false);
  const [visual, setVisual] = useState(true);
  const [audio, setAudio] = useState(true);
  const [topK, setTopK] = useState(10);

  // Determine search type based on selections
  const getSearchType = () => {
    if (visual && audio) return 'vector';
    if (visual && !audio) return 'visual';
    if (!visual && audio) return 'audio';
    return 'vector'; // default
  };

  const handle_submit = (e) => {
    e.preventDefault();
    if (query.trim()) {
      const searchType = getSearchType();
      console.log(searchType)
      onSearch(query, searchType, topK);
    }
  };

  const clear_query = () => {
    updateQuery('');
  };

  const handleVisualChange = (e) => {
    const newVisual = e.target.checked;
    setVisual(newVisual);
    const newSearchType = newVisual && audio ? 'vector' : (newVisual ? 'visual' : 'audio');
    onSearchTypeChange?.(newSearchType);
  };

  const handleAudioChange = (e) => {
    const newAudio = e.target.checked;
    setAudio(newAudio);
    const newSearchType = visual && newAudio ? 'vector' : (visual ? 'visual' : 'audio');
    onSearchTypeChange?.(newSearchType);
  };

  return (
    <form onSubmit={handle_submit} className="w-full">
      <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
        {/* Search Input */}
        <div className="relative flex-1 min-w-0">
          <div className="absolute left-6 top-1/2 -translate-y-1/2 text-gray-400">
            <Search size={20} />
          </div>
          <input
            type="text"
            value={query}
            onChange={(e) => updateQuery(e.target.value)}
            placeholder="Search videos, actions, or objects..."
            className="w-full py-4 pl-14 pr-16 text-base sm:text-lg rounded-2xl border border-blue-200 focus:outline-none focus:ring-4 focus:ring-blue-200 focus:border-blue-400 shadow-sm hover:shadow-md transition-all"
            disabled={isLoading}
          />
          
          {query && !isLoading && (
            <button
              type="button"
              onClick={clear_query}
              className="absolute right-6 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
            >
              <X size={20} />
            </button>
          )}
          
          {isLoading && (
            <div className="absolute right-6 top-1/2 -translate-y-1/2">
              <Loader2 size={20} className="animate-spin text-gray-600" />
            </div>
          )}
        </div>

        {/* Dropdown Button */}
        <div className="relative self-end sm:self-auto">
          <button
            type="button"
            onClick={() => setShowDropdown(!showDropdown)}
            className="flex items-center gap-2 px-4 py-4 bg-gray-100 hover:bg-gray-200 rounded-2xl border border-gray-200 transition-colors w-full sm:w-auto justify-center"
            disabled={isLoading}
          >
            <div className="w-5 h-5 flex items-center justify-center">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
              </svg>
            </div>
            <ChevronDown size={18} />
          </button>

          {/* Dropdown Menu */}
          {showDropdown && (
            <div className="absolute right-0 mt-2 w-64 bg-white rounded-xl border border-gray-200 shadow-lg z-50">
              <div className="p-4">
                <h3 className="text-sm font-semibold text-gray-700 mb-3">Additional Configurations</h3>
                <p className="text-xs text-gray-500 mb-4">Select search options</p>
                
                <div className="space-y-3">
                  {/* Visual Checkbox */}
                  <label className="flex items-center gap-3 cursor-pointer hover:bg-gray-50 p-2 rounded">
                    <input
                      type="checkbox"
                      checked={visual}
                      onChange={handleVisualChange}
                      className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-2 focus:ring-blue-500"
                    />
                    <span className="text-sm font-medium text-gray-700">Visual</span>
                  </label>

                  {/* Audio Checkbox */}
                  <label className="flex items-center gap-3 cursor-pointer hover:bg-gray-50 p-2 rounded">
                    <input
                      type="checkbox"
                      checked={audio}
                      onChange={handleAudioChange}
                      className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-2 focus:ring-blue-500"
                    />
                    <span className="text-sm font-medium text-gray-700">Audio</span>
                  </label>

                  {/* Top K Input */}
                  {/* <div className="flex items-center gap-3 p-2">
                    <label className="text-sm font-medium text-gray-700 flex-1">
                      Results (n)
                    </label>
                    <input
                      type="number"
                      min="1"
                      max="100"
                      value={topK}
                      onChange={(e) => setTopK(Math.max(1, parseInt(e.target.value)))}
                      className="w-16 px-2 py-1 border border-gray-300 rounded text-sm text-center focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div> */}
                </div>

                {/* Search Type Display */}
                <div className="mt-4 pt-3 border-t border-gray-200">
                  <p className="text-xs text-gray-500">
                    Search type: <span className="font-semibold text-gray-700">{getSearchType()}</span>
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </form>
  );
};

export default SearchBar;