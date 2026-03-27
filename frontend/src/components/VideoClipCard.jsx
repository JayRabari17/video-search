import React, { useRef, useState, useCallback } from 'react';
import { Play, Clock, TrendingUp, Loader2 } from 'lucide-react';
import { formatTimestamp } from '../utils/formatTime';
import { use_thumbnail } from '../hooks/useThumbnail';

const VideoClipCard = ({ clip, onClick, from }) => {
  const { video_id, video_path, timestamp_start, timestamp_end, clip_text, score, presigned_url, thumbnail_path, video_duration_sec } = clip;

  // Normalize score to 0-100 range
  const rawScore = typeof score === 'number' ? score : 0;
  const normalizedScore = rawScore > 1 ? rawScore : Math.abs(rawScore) * 100;
  const clampedScore = Math.max(0, Math.min(normalizedScore, 100));

  const evaluationScore = Math.min(clampedScore, 80);

  let confidenceLabel = 'LOW';
  let indicatorBg = 'bg-red-500';

  if (evaluationScore >= 65 && evaluationScore < 80) {
    confidenceLabel = 'MEDIUM';
    indicatorBg = 'bg-yellow-500';
  } else if (evaluationScore >= 80) {
    confidenceLabel = 'HIGH';
    indicatorBg = 'bg-green-500';
  }

  // Use thumbnail_path if available (presigned URL from backend), otherwise generate from video
  const videoUrl = presigned_url || video_path;
  const { thumbnail, isLoading: thumbnailLoading, error: thumbnailError } = use_thumbnail(
    videoUrl,
    video_id,
    timestamp_start,
    thumbnail_path  // Pass thumbnail_path as fallback
  );

  const videoRef = useRef(null);
  const [isHovering, setIsHovering] = useState(false);

  const handleMouseEnter = useCallback(() => {
    if (!videoUrl) return;
    setIsHovering(true);
    const videoEl = videoRef.current;
    if (videoEl) {
      videoEl.volume = 0.5; // Set default volume to 50%
      videoEl.currentTime = timestamp_start || 0;
      const playPromise = videoEl.play();
      if (playPromise?.catch) {
        playPromise.catch(() => { });
      }
    }
  }, [timestamp_start, videoUrl]);

  const handleMouseLeave = useCallback(() => {
    const videoEl = videoRef.current;
    if (videoEl) {
      videoEl.pause();
      videoEl.currentTime = timestamp_start || 0;
    }
    setIsHovering(false);
  }, [timestamp_start]);

  const handleTimeUpdate = useCallback(() => {
    const videoEl = videoRef.current;
    if (videoEl && timestamp_end !== undefined) {
      if (videoEl.currentTime >= timestamp_end) {
        videoEl.pause();
        videoEl.currentTime = timestamp_start || 0;
      }
    }
  }, [timestamp_end, timestamp_start]);

  return (
    <div
      className="cursor-pointer group"
      onClick={() => onClick(clip)}
    >
      {/* Video Card Container */}
      <div
        className="bg-white rounded-2xl shadow-md hover:shadow-xl hover:border-blue-200 border border-transparent transition-all duration-300 overflow-hidden"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        {/* Video Thumbnail */}
        <div className="relative w-full aspect-video bg-gray-200 flex items-center justify-center overflow-hidden">
          {/* Loading state */}
          {thumbnailLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-gray-200">
              <Loader2 size={40} className="text-gray-400 animate-spin" />
            </div>
          )}

          {/* Error state */}
          {thumbnailError && !thumbnail && (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-200 text-gray-600 p-4">
              <div className="text-red-400 text-sm text-center mb-2">
                Unable to load thumbnail
              </div>
              <div className="text-xs text-gray-400 text-center">
                CORS not enabled on video
              </div>
            </div>
          )}

          {/* Actual thumbnail */}
          {thumbnail && (
            <img
              src={thumbnail}
              alt={`Thumbnail at ${formatTimestamp(timestamp_start)}`}
              className={`absolute inset-0 w-full h-full object-cover transition-opacity duration-200 ${isHovering ? 'opacity-0' : 'opacity-100'}`}
              loading="lazy"
            />
          )}

          {/* Hover video preview */}
          {videoUrl && (
            <video
              ref={videoRef}
              src={videoUrl}
              playsInline
              preload="none"
              className={`absolute inset-0 w-full h-full object-cover transition-opacity duration-200 ${isHovering ? 'opacity-100' : 'opacity-0'}`}
              onTimeUpdate={handleTimeUpdate}
            />
          )}

          {
            from !== "Marengo 3" && (
              <div className={`absolute top-2 right-2 sm:right-24 px-3 py-1 rounded text-xs font-semibold text-white ${indicatorBg}`}>
                {confidenceLabel}
              </div>
            )
          }

          {/* Timeline bar - floating above bottom */}
          <div className="absolute bottom-2 left-0.5 right-0.5 h-1.5 bg-gray-400/50 rounded">
            {/* Calculate clip position and width based on actual video duration or 6-minute default */}
            {timestamp_start !== undefined && timestamp_end !== undefined && (
              <>
                {/* Clip duration highlight */}
                <div
                  className="absolute h-full bg-orange-600/80 rounded"
                  style={{
                    left: `${(timestamp_start / (video_duration_sec || 360)) * 100}%`,
                    width: `${((timestamp_end - timestamp_start) / (video_duration_sec || 360)) * 100}%`,
                  }}
                />
              </>
            )}
          </div>

          {/* Timestamp overlay */}
          <div className="absolute top-2 right-2 bg-black/70 text-white text-xs px-2 py-1 rounded">
            {formatTimestamp(timestamp_start)} - {formatTimestamp(timestamp_end)}
          </div>
        </div>
      </div>

      {/* Title Below Card */}
      <div className="pt-2 px-1">
        <p className="text-sm font-medium text-gray-800 line-clamp-2 leading-snug">
          {clip_text || 'Video clip segment'}
        </p>
      </div>
    </div>
  );
};

export default VideoClipCard;
