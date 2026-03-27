import { useRef, useEffect } from 'react';
import { X, ExternalLink } from 'lucide-react';
import { formatTimestamp } from '../utils/formatTime';
import JsonDisplay from './JsonDisplay';

const VideoPlayer = ({ clip, onClose }) => {
  const videoRef = useRef(null);

  useEffect(() => {
    const videoElement = videoRef.current;

    if (!videoElement || !clip) {
      return;
    }

    // Set default volume to 50%
    videoElement.volume = 0.5;
    
    videoElement.currentTime = clip.timestamp_start;
    const playPromise = videoElement.play();

    let autoPaused = false;

    const handleTimeUpdate = () => {
      // if (!autoPaused && videoElement.currentTime >= clip.timestamp_end) {
      //   autoPaused = true;
      //   videoElement.pause();
      //   videoElement.removeEventListener('timeupdate', handleTimeUpdate);
      // }
    };

    const handlePlay = () => {
      if (videoElement.currentTime >= clip.timestamp_end && autoPaused) {
        // User resumed playback intentionally; keep playing
        videoElement.removeEventListener('timeupdate', handleTimeUpdate);
      }
    };

    videoElement.addEventListener('timeupdate', handleTimeUpdate);
    videoElement.addEventListener('play', handlePlay);

    return () => {
      videoElement.removeEventListener('timeupdate', handleTimeUpdate);
      videoElement.removeEventListener('play', handlePlay);
      if (playPromise !== undefined) {
        playPromise.catch(() => {});
      }
    };
  }, [clip]);

  if (!clip) return null;

  return (
    <div className="fixed inset-0 bg-black/90 backdrop-blur-sm z-50 flex items-center justify-center p-2 sm:p-6 lg:p-8 animate-fade-in">
      <div className="bg-white rounded-2xl shadow-2xl max-w-6xl w-full max-h-[92vh] sm:max-h-[85vh] overflow-hidden animate-slide-up">
        {/* Header */}
        <div className="flex items-center justify-between px-4 sm:px-6 py-3 sm:py-4 border-b border-gray-200">
          <div className="flex items-center gap-3">
            <div className="px-3 py-1 bg-green-500 text-white text-xs font-bold rounded">
              CLIP
            </div>
            <div>
              <h3 className="text-base font-semibold text-gray-900">
                {clip.video_id.substring(0, 20)}...
              </h3>
              <p className="text-xs text-gray-500">
                {formatTimestamp(clip.timestamp_start)} - {formatTimestamp(clip.timestamp_end)}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <X size={20} className="text-gray-600" />
          </button>
        </div>

        <div className="flex flex-col lg:flex-row h-[calc(92vh-64px)] sm:h-[calc(85vh-73px)]">
          {/* Left Side - Video Player */}
          <div className="w-full lg:w-[55%] bg-black flex items-center justify-center">
            <video
              ref={videoRef}
              src={clip.presigned_url || clip.video_path}
              controls
              className="w-full h-full object-contain"
              controlsList="nodownload"
            >
              Your browser does not support the video tag.
            </video>
          </div>

          {/* Right Side - JSON Response */}
          <div className="w-full lg:w-[45%] flex flex-col bg-gray-50 min-h-0">
            <div className="px-4 py-3 bg-white border-b border-gray-200 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-gray-700">Metadata</span>
                <span className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded">
                  JSON
                </span>
              </div>
              <button className="px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100 rounded transition-colors">
                Copy IDs
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden flex items-center justify-center p-3 sm:p-4">
              <div className="w-full h-full">
                <JsonDisplay data={clip} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default VideoPlayer;
