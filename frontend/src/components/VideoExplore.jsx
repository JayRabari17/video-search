import React, { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { Video, Loader2, AlertCircle, Play, X } from 'lucide-react';
import { listAllVideos } from '../services/api';

const VideoThumbnail = ({ videoUrl, videoId }) => {
  const [thumbnail, setThumbnail] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const videoRef = useRef(null);

  useEffect(() => {
    const generateThumbnail = async () => {
      try {
        const video = document.createElement('video');
        video.crossOrigin = 'anonymous';
        video.src = videoUrl;
        video.currentTime = 1; // Capture frame at 1 second

        video.addEventListener('loadeddata', () => {
          const canvas = document.createElement('canvas');
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
          const ctx = canvas.getContext('2d');
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          
          const thumbnailUrl = canvas.toDataURL('image/jpeg', 0.8);
          setThumbnail(thumbnailUrl);
          setIsLoading(false);
        });

        video.addEventListener('error', () => {
          setIsLoading(false);
        });

        video.load();
      } catch (err) {
        console.error('Error generating thumbnail:', err);
        setIsLoading(false);
      }
    };

    if (videoUrl) {
      generateThumbnail();
    }
  }, [videoUrl]);

  if (isLoading) {
    return (
      <div className="absolute inset-0 flex items-center justify-center bg-gray-200">
        <Loader2 size={40} className="text-blue-400 animate-spin" />
      </div>
    );
  }

  if (!thumbnail) {
    return (
      <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-blue-100 to-blue-200">
        <Video size={48} className="text-blue-600" />
      </div>
    );
  }

  return (
    <img 
      src={thumbnail} 
      alt="Video thumbnail"
      className="absolute inset-0 w-full h-full object-cover"
      loading="lazy"
    />
  );
};

const VideoExplore = () => {
  const [videos, setVideos] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedVideo, setSelectedVideo] = useState(null);

  const fetch_videos = async () => {
    setIsLoading(true);
    setError(null);
    
    try {
      const data = await listAllVideos();
      
      // Transform API response to component format
      const transformedVideos = data.videos.map(video => ({
        id: video.video_id,
        title: video.title || `Video ${video.video_id.substring(0, 8)}`,
        videoUrl: video.video_path,  // Use presigned URL for video access
        duration: formatDuration(video.duration),
        uploadDate: video.upload_date || 'Unknown',
        videoPath: video.video_path,  // Presigned URL from backend
        clipsCount: video.clips_count
      }));
      
      setVideos(transformedVideos);
    } catch (err) {
      console.error('Error fetching videos:', err);
      setError('Failed to load videos. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const formatDuration = (seconds) => {
    if (!seconds) return 'N/A';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  };

  useEffect(() => {
    fetch_videos();
  }, []);

  return (
    <motion.section
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6 }}
      className="w-full"
    >
      {/* Header */}
      <div className="text-center mb-10">
        <h1 className="text-3xl sm:text-4xl font-extrabold bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent mb-2">
          Explore All Videos
        </h1>
        <p className="text-blue-600 text-lg">
          Browse all videos from your library
        </p>
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="text-center py-16">
          <div className="inline-block w-16 h-16 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin mb-4"></div>
          <p className="text-gray-600">Loading videos...</p>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="mb-8 p-4 bg-red-50 border border-red-200 rounded-xl flex items-center gap-3 text-red-700 max-w-2xl mx-auto">
          <AlertCircle size={20} />
          <span>{error}</span>
        </div>
      )}

      {/* Videos Grid */}
      {!isLoading && !error && videos.length > 0 && (
        <div className="w-full max-w-7xl mx-auto">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-8">
            {videos.map((video, index) => (
              <motion.div
                key={video.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.1 }}
                onClick={() => setSelectedVideo(video)}
                className="bg-white rounded-3xl shadow-md hover:shadow-xl transition-all duration-300 overflow-hidden cursor-pointer group"
              >
                {/* Video Thumbnail */}
                <div className="relative h-44 sm:h-52 bg-gray-200 flex items-center justify-center overflow-hidden">
                  <VideoThumbnail videoUrl={video.videoUrl} videoId={video.id} />
                  
                  {/* Duration overlay */}
                  {video.duration !== 'N/A' && (
                    <div className="absolute bottom-2 right-2 bg-black/70 text-white text-xs px-2 py-1 rounded">
                      {video.duration}
                    </div>
                  )}
                </div>
                
                {/* Card content */}
                <div className="p-4">
                  <p className="text-md font-semibold truncate text-gray-900">
                    {video.title}
                  </p>
                  <div className="flex items-center justify-between mt-2">
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      )}

      {/* Empty State */}
      {!isLoading && !error && videos.length === 0 && (
        <div className="text-center py-16">
          <div className="max-w-md mx-auto">
            <div className="w-24 h-24 bg-gradient-to-br from-blue-100 to-blue-200 rounded-full flex items-center justify-center mx-auto mb-6">
              <Video size={48} className="text-blue-600" />
            </div>
            <h3 className="text-2xl font-bold text-gray-900 mb-3">
              No Videos Yet
            </h3>
            <p className="text-gray-600 mb-6">
              Upload your first video to get started
            </p>
          </div>
        </div>
      )}

      {/* Info Box */}
      {videos.length > 0 && (
        <div className="mt-12 p-6 bg-blue-50 border border-blue-200 rounded-xl max-w-4xl mx-auto">
          <h4 className="font-semibold text-blue-900 mb-2 flex items-center gap-2">
            <Video size={20} />
            Video Library
          </h4>
          <p className="text-sm text-blue-800">
            Showing all videos from your OpenSearch index. Each video has been processed and indexed for semantic search.
          </p>
          <div className="mt-3 flex items-center gap-4 text-sm text-blue-700">
            <span className="font-medium">Total Videos: {videos.length}</span>
            {/* <span className="font-medium">Total Clips: {videos.reduce((sum, v) => sum + v.clipsCount, 0)}</span> */}
          </div>
        </div>
      )}

      {/* Video Player Popup */}
      {selectedVideo && (
        <div className="fixed inset-0 bg-black/90 backdrop-blur-sm z-50 flex items-center justify-center p-2 sm:p-6 lg:p-8 animate-fade-in">
          <div className="bg-white rounded-2xl shadow-2xl max-w-5xl w-full max-h-[92vh] sm:max-h-[85vh] overflow-hidden animate-slide-up">
            {/* Header */}
            <div className="flex items-center justify-between px-4 sm:px-6 py-3 sm:py-4 border-b border-gray-200">
              <div className="flex items-center gap-3">
                <div className="px-3 py-1 bg-blue-500 text-white text-xs font-bold rounded">
                  VIDEO
                </div>
                <div>
                  <h3 className="text-base font-semibold text-gray-900">
                    {selectedVideo.title}
                  </h3>
                  <p className="text-xs text-gray-500">
                    {selectedVideo.clipsCount} clips • {selectedVideo.duration}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setSelectedVideo(null)}
                className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <X size={20} className="text-gray-600" />
              </button>
            </div>

            {/* Video Player */}
            <div className="bg-black flex items-center justify-center h-[calc(92vh-64px)] sm:h-[calc(85vh-73px)]">
              <video
                src={selectedVideo.videoPath}
                controls
                autoPlay
                className="w-full h-full object-contain"
                controlsList="nodownload"
              >
                Your browser does not support the video tag.
              </video>
            </div>
          </div>
        </div>
      )}
    </motion.section>
  );
};

export default VideoExplore;
