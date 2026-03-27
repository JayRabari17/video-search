import React, { useState } from 'react';
import SearchBarMarengo3 from './SearchBarMarengo3';
import ResultsGrid from './ResultsGrid';
import VideoPlayerMarengo3 from './VideoPlayerMarengo3';
import { searchClipsMarengo3 } from '../services/api';
import { AlertCircle, Search } from 'lucide-react';
import { motion } from 'framer-motion';

function SearchMarengo3() {
  const [clips, setClips] = useState([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedClip, setSelectedClip] = useState(null);
  const [hasSearched, setHasSearched] = useState(false);

  const handle_search = async (searchQuery, searchType, topK = 20, imageResponse = null, imageFile = null, categories = null, minRelevance = null, maxSegmentsPerVideo = null) => {
    setIsLoading(true);
    setError(null);
    setQuery(searchQuery || '');
    setHasSearched(true);

    try {
      // If imageResponse is provided (from image search), use it directly
      if (imageResponse) {
        console.log("Using image search response (Marengo 3)");
        setClips(imageResponse.clips);
        setTotal(imageResponse.total);
      }
      // Otherwise perform unified search (text, image, or combined)
      else {
        console.log("Performing unified search (Marengo 3):", {
          hasText: !!searchQuery,
          hasImage: !!imageFile,
          topK,
          searchType,
          categories,
          minRelevance,
          maxSegmentsPerVideo
        });
        const response = await searchClipsMarengo3(searchQuery, topK, searchType, imageFile, categories, minRelevance, maxSegmentsPerVideo);
        setClips(response.clips);
        setTotal(response.total);
      }
    } catch (err) {
      setError('Failed to search videos (Marengo 3). Please try again.');
      console.error('Search error (Marengo 3):', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handle_clip_click = (clip) => {
    setSelectedClip(clip);
  };

  const close_player = () => {
    setSelectedClip(null);
  };

  return (
    <div className="w-full h-full flex flex-col">
      {/* Centered Search (Initial State) or Top Search (After Search) */}
      <motion.div
        layout
        initial={false}
        animate={{
          justifyContent: hasSearched ? 'flex-start' : 'center',
          paddingTop: hasSearched ? '2rem' : '0',
        }}
        transition={{ duration: 0.5, ease: 'easeInOut' }}
        className="flex flex-col items-center w-full"
        style={{ minHeight: hasSearched ? 'auto' : '80vh' }}
      >
        {/* Hero Section - Only show when not searched */}
        {!hasSearched && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.6 }}
            className="text-center mb-8"
          >
            <div className="flex items-center justify-center gap-2 mb-3">
              <h1 className="text-5xl font-extrabold bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">
                Where should we begin?
              </h1>
            </div>
            <p className="text-blue-600 text-lg">
              Search your video library with natural language
            </p>
          </motion.div>
        )}

        {/* Search Bar - Animates from center to top */}
        <motion.div
          layout
          transition={{ duration: 0.5, ease: 'easeInOut' }}
          className="w-full max-w-2xl mb-6"
        >
          <SearchBarMarengo3
            onSearch={handle_search}
            isLoading={isLoading}
            queryValue={query}
            onQueryChange={setQuery}
          />
        </motion.div>

        {/* Suggestion chips - Only show when not searched */}
        {!hasSearched && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-wrap gap-2 justify-center max-w-4xl"
          >
            <button
              onClick={() => {
                handle_search('people dancing');
              }}
              className="px-4 py-2 bg-white border border-blue-200 rounded-full hover:border-blue-600 hover:bg-blue-50 transition-all text-sm text-gray-700"
            >
              people dancing
            </button>
            <button
              onClick={() => {
                handle_search('scenes with dinosaur')
              }
              }
              className="px-4 py-2 bg-white border border-blue-200 rounded-full hover:border-blue-600 hover:bg-blue-50 transition-all text-sm text-gray-700"
            >
              scenes with dinosaur
            </button>
            <button
              onClick={() => {
                handle_search('person drinking mountain dew')
              }
              }
              className="px-4 py-2 bg-white border border-blue-200 rounded-full hover:border-blue-600 hover:bg-blue-50 transition-all text-sm text-gray-700"
            >
              person drinking mountain dew
            </button>
          </motion.div>
        )}
      </motion.div>

      {/* Results Section - Only show after search */}
      {hasSearched && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="w-full px-0 sm:px-6 lg:px-8"
        >
          {/* Error Message */}
          {error && (
            <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl flex items-center gap-3 text-red-700 max-w-2xl mx-auto">
              <AlertCircle size={20} />
              <span>{error}</span>
            </div>
          )}

          {/* Loading State */}
          {isLoading && (
            <div className="text-center py-16">
              <div className="inline-block w-16 h-16 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin mb-4"></div>
              <p className="text-gray-600">Searching videos....</p>
            </div>
          )}

          {/* Results */}
          {!isLoading && clips.length > 0 && (
            <div className="w-full max-w-8xl mx-auto">
              <ResultsGrid
                clips={clips}
                total={total}
                query={query}
                onClipClick={handle_clip_click}
                from={"Marengo 3"}
              />
            </div>
          )}

          {/* No Results */}
          {!isLoading && query && clips.length === 0 && (
            <div className="text-center py-16">
              <div className="w-24 h-24 bg-gradient-to-br from-blue-100 to-blue-200 rounded-full flex items-center justify-center mx-auto mb-6">
                <Search size={48} className="text-blue-600" />
              </div>
              <h3 className="text-2xl font-bold text-gray-900 mb-3">
                No results found
              </h3>
              <p className="text-gray-600">
                Try a different search query
              </p>
            </div>
          )}
        </motion.div>
      )}

      {/* Video Player Modal */}
      {selectedClip && (
        <VideoPlayerMarengo3
          clip={selectedClip}
          allClips={clips}
          onClose={close_player}
          onClipSelect={setSelectedClip}
        />
      )}
    </div>
  );
}

export default SearchMarengo3;
