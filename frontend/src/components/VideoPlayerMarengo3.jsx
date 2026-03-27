import React, { useRef, useEffect, useState } from 'react';
import { 
  X, Copy, ThumbsUp, ThumbsDown, MessageSquare, 
  Play, Pause, Volume2, VolumeX, Maximize, Minimize, 
  Settings, PictureInPicture, ChevronRight
} from 'lucide-react';
import { formatTimestamp } from '../utils/formatTime';

const VideoPlayerMarengo3 = ({ clip, allClips, onClose, onClipSelect }) => {
  const videoRef = useRef(null);
  const playerContainerRef = useRef(null);
  const timelineRef = useRef(null);
  
  // State
  const [isPlaying, setIsPlaying] = useState(false);
  const [videoDuration, setVideoDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [volume, setVolume] = useState(0.5);
  const [isMuted, setIsMuted] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showControls, setShowControls] = useState(true);
  const [showSpeedMenu, setShowSpeedMenu] = useState(false);

  // Constants
  const PLAYBACK_SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];

  useEffect(() => {
    const videoElement = videoRef.current;
    if (!videoElement || !clip) return;

    // Initial setup
    videoElement.volume = volume;
    videoElement.currentTime = clip.timestamp_start;
    
    // Auto-play
    const playPromise = videoElement.play();
    if (playPromise !== undefined) {
      playPromise.catch(() => {});
    }

    const handlePlay = () => setIsPlaying(true);
    const handlePause = () => setIsPlaying(false);
    const handleLoadedMetadata = () => setVideoDuration(videoElement.duration);
    const handleTimeUpdate = () => setCurrentTime(videoElement.currentTime);
    const handleVolumeChange = () => {
      setVolume(videoElement.volume);
      setIsMuted(videoElement.muted);
    };
    const handleRateChange = () => setPlaybackRate(videoElement.playbackRate);

    videoElement.addEventListener('play', handlePlay);
    videoElement.addEventListener('pause', handlePause);
    videoElement.addEventListener('loadedmetadata', handleLoadedMetadata);
    videoElement.addEventListener('timeupdate', handleTimeUpdate);
    videoElement.addEventListener('volumechange', handleVolumeChange);
    videoElement.addEventListener('ratechange', handleRateChange);

    return () => {
      videoElement.removeEventListener('play', handlePlay);
      videoElement.removeEventListener('pause', handlePause);
      videoElement.removeEventListener('loadedmetadata', handleLoadedMetadata);
      videoElement.removeEventListener('timeupdate', handleTimeUpdate);
      videoElement.removeEventListener('volumechange', handleVolumeChange);
      videoElement.removeEventListener('ratechange', handleRateChange);
    };
  }, [clip]);

  // Fullscreen handler
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  // Controls visibility timeout
  useEffect(() => {
    let timeout;
    const handleMouseMove = () => {
      setShowControls(true);
      clearTimeout(timeout);
      timeout = setTimeout(() => {
        if (isPlaying) setShowControls(false);
      }, 3000);
    };

    const container = playerContainerRef.current;
    if (container) {
      container.addEventListener('mousemove', handleMouseMove);
      container.addEventListener('mouseleave', () => {
        if (isPlaying) setShowControls(false);
      });
    }

    return () => {
      if (container) {
        container.removeEventListener('mousemove', handleMouseMove);
      }
      clearTimeout(timeout);
    };
  }, [isPlaying]);

  // Actions
  const togglePlay = () => {
    if (videoRef.current) {
      if (isPlaying) videoRef.current.pause();
      else videoRef.current.play();
    }
  };

  const toggleMute = () => {
    if (videoRef.current) {
      videoRef.current.muted = !isMuted;
    }
  };

  const handleVolumeSlider = (e) => {
    const newVolume = parseFloat(e.target.value);
    if (videoRef.current) {
      videoRef.current.volume = newVolume;
      videoRef.current.muted = newVolume === 0;
    }
  };

  const handleTimelineClick = (e) => {
    if (!timelineRef.current || !videoRef.current) return;
    const rect = timelineRef.current.getBoundingClientRect();
    const percent = Math.min(Math.max(0, e.clientX - rect.left), rect.width) / rect.width;
    videoRef.current.currentTime = percent * videoDuration;
  };

  const toggleFullscreen = async () => {
    if (!playerContainerRef.current) return;
    try {
      if (!document.fullscreenElement) {
        await playerContainerRef.current.requestFullscreen();
      } else {
        await document.exitFullscreen();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const togglePiP = async () => {
    if (!videoRef.current) return;
    try {
      if (document.pictureInPictureElement) {
        await document.exitPictureInPicture();
      } else {
        await videoRef.current.requestPictureInPicture();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const changeSpeed = (speed) => {
    if (videoRef.current) {
      videoRef.current.playbackRate = speed;
      setShowSpeedMenu(false);
    }
  };

  // Helper data - get all clips from same video, maintaining search result order
  const allMatchesFromVideo = allClips.filter(c => c.video_id === clip.video_id);

  const getAbsoluteIndex = (clipToFind) => {
    const index = allClips.findIndex(c => 
      c.video_id === clipToFind.video_id && c.timestamp_start === clipToFind.timestamp_start
    );
    return index !== -1 ? index + 1 : 1;
  };

  const currentClipIndex = getAbsoluteIndex(clip);

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/80 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Side Panel */}
      <div className="relative w-full max-w-full sm:max-w-md md:max-w-lg lg:max-w-xl h-full bg-white shadow-2xl flex flex-col animate-in slide-in-from-right duration-300">
        
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 bg-white z-10">
          <h2 className="text-sm font-semibold text-gray-800 line-clamp-1 flex-1 mr-4">
            {clip.video_name || 'Untitled Video'}
          </h2>
          <button 
            onClick={onClose}
            className="p-1.5 hover:bg-gray-100 rounded-full transition-colors text-gray-500 hover:text-gray-700"
          >
            <X size={20} />
          </button>
        </div>

        {/* Action Bar */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100 bg-gray-50/50">
          <button className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-200 rounded-md text-xs font-medium text-gray-600 hover:bg-gray-50 hover:border-gray-300 transition-all shadow-sm">
            <Copy size={14} />
            <span>Copy IDs</span>
          </button>
          <div className="flex items-center gap-2">
            <button className="p-1.5 hover:bg-white hover:shadow-sm border border-transparent hover:border-gray-200 rounded-md text-gray-500 transition-all">
              <ThumbsUp size={16} />
            </button>
            <button className="p-1.5 hover:bg-white hover:shadow-sm border border-transparent hover:border-gray-200 rounded-md text-gray-500 transition-all">
              <ThumbsDown size={16} />
            </button>
          </div>
        </div>

        {/* Main Video Player Container */}
        <div 
          ref={playerContainerRef}
          className={`relative bg-black group ${isFullscreen ? 'fixed inset-0 z-[60]' : 'w-full aspect-video'}`}
        >
          {/* Video Area */}
          <div 
            className="absolute inset-0 w-full h-full cursor-pointer"
            onClick={togglePlay}
          >
            <video
              ref={videoRef}
              src={clip.presigned_url || clip.video_path}
              className="w-full h-full object-contain"
              playsInline
            />

            {/* Center Play/Pause Overlay */}
            {!isPlaying && (
              <div 
                className="absolute inset-0 flex items-center justify-center bg-black/20"
              >
                <div className="w-16 h-16 bg-white/10 backdrop-blur-md rounded-full flex items-center justify-center hover:bg-white/20 transition-all hover:scale-105 shadow-lg border border-white/10">
                  <Play className="w-8 h-8 text-white ml-1" fill="currentColor" />
                </div>
              </div>
            )}
          </div>

          {/* Custom Controls Overlay Container */}
          <div 
            className={`absolute inset-0 flex flex-col justify-end pointer-events-none transition-opacity duration-300 ${showControls ? 'opacity-100' : 'opacity-0'}`}
          >
            <div className="w-full bg-gradient-to-t from-black/90 via-black/60 to-transparent px-4 pb-4 pt-10 pointer-events-auto">
              {/* Timeline (Top of Control Bar) */}
              <div className="w-full flex items-center gap-3 mb-1">
                <span className="text-[10px] font-mono text-gray-300 min-w-[35px] text-right">
                  {formatTimestamp(currentTime)}
                </span>
                
                <div 
                  className="relative flex-1 h-1.5 bg-white/20 rounded-full cursor-pointer group/timeline hover:h-2 transition-all"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleTimelineClick(e);
                  }}
                  ref={timelineRef}
                >
                  {/* Highlighted Clip Range */}
                  {videoDuration > 0 && (
                    <div
                      className="absolute h-full bg-orange-500 z-0 rounded-full pointer-events-none"
                      style={{
                        left: `${(clip.timestamp_start / videoDuration) * 100}%`,
                        width: `${((clip.timestamp_end - clip.timestamp_start) / videoDuration) * 100}%`,
                      }}
                    />
                  )}

                  {/* Progress Bar */}
                  <div
                    className="absolute h-full bg-blue-500 z-10 rounded-full relative"
                    style={{ width: `${(currentTime / videoDuration) * 100}%` }}
                  >
                    <div className="absolute right-0 top-1/2 -translate-y-1/2 w-3 h-3 bg-white rounded-full shadow-md scale-0 group-hover/timeline:scale-100 transition-transform" />
                  </div>
                </div>

                <span className="text-[10px] font-mono text-gray-300 min-w-[35px]">
                  {formatTimestamp(videoDuration)}
                </span>
              </div>

              {/* Controls Row (Bottom of Control Bar) */}
              <div className="flex items-center justify-between w-full text-white px-1">
                
                {/* Left Controls: Play & Volume */}
                <div className="flex items-center gap-3">
                  <button onClick={(e) => { e.stopPropagation(); togglePlay(); }} className="hover:text-blue-400 transition-colors p-1">
                    {isPlaying ? <Pause size={24} fill="currentColor" /> : <Play size={24} fill="currentColor" />}
                  </button>

                  <div className="flex items-center gap-2 group/volume">
                    <button onClick={(e) => { e.stopPropagation(); toggleMute(); }} className="hover:text-blue-400 transition-colors p-1">
                      {isMuted || volume === 0 ? <VolumeX size={20} /> : <Volume2 size={20} />}
                    </button>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.05"
                      value={isMuted ? 0 : volume}
                      onChange={handleVolumeSlider}
                      onClick={(e) => e.stopPropagation()}
                      style={{
                        background: `linear-gradient(to right, white ${(isMuted ? 0 : volume) * 100}%, rgba(255,255,255,0.3) ${(isMuted ? 0 : volume) * 100}%)`
                      }}
                      className="w-0 overflow-hidden group-hover/volume:w-20 transition-all duration-300 h-1 rounded-lg appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:rounded-full hover:[&::-webkit-slider-thumb]:bg-blue-400"
                    />
                  </div>
                </div>

                {/* Right Controls: Speed, PiP, Fullscreen */}
                <div className="flex items-center gap-2">
                  {/* Speed Control */}
                  <div className="relative">
                    <button 
                      onClick={() => setShowSpeedMenu(!showSpeedMenu)}
                      className="text-xs font-bold hover:text-blue-400 transition-colors bg-white/10 px-2 py-1 rounded hover:bg-white/20 min-w-[32px]"
                    >
                      {playbackRate}x
                    </button>
                    {showSpeedMenu && (
                      <div className="absolute bottom-full right-0 mb-2 bg-black/90 border border-white/10 rounded-lg overflow-hidden shadow-xl min-w-[60px] py-1 z-20">
                        {PLAYBACK_SPEEDS.map(speed => (
                          <button
                            key={speed}
                            onClick={() => changeSpeed(speed)}
                            className={`w-full px-2 py-1 text-left text-xs hover:bg-white/10 ${playbackRate === speed ? 'text-blue-400 font-bold' : 'text-gray-300'}`}
                          >
                            {speed}x
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  <button 
                    onClick={togglePiP} 
                    className="hover:text-blue-400 transition-colors p-1.5 hover:bg-white/10 rounded-full"
                    title="Picture in Picture"
                  >
                    <PictureInPicture size={20} />
                  </button>

                  <button 
                    onClick={toggleFullscreen} 
                    className="hover:text-blue-400 transition-colors p-1.5 hover:bg-white/10 rounded-full"
                    title="Fullscreen"
                  >
                    {isFullscreen ? <Minimize size={20} /> : <Maximize size={20} />}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Matches List Header */}
        <div className="px-4 py-3 border-b border-gray-100 bg-white">
          <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
            <span>Matches in this video</span>
            <span className="bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full text-xs">
              {allMatchesFromVideo.length}
            </span>
          </h3>
        </div>

        {/* Scrollable Matches List */}
        <div className="flex-1 overflow-y-auto p-3 sm:p-4 space-y-4 bg-gray-50">
          {allMatchesFromVideo.map((match, idx) => {
            const matchAbsoluteIndex = getAbsoluteIndex(match);
            const isCurrentClip = match.timestamp_start === clip.timestamp_start;
            
            return (
              <div 
                key={`${match.video_id}-${match.timestamp_start}-${idx}`}
                className={`group rounded-xl p-4 border shadow-sm transition-all relative overflow-hidden ${
                  isCurrentClip 
                    ? 'bg-white border-blue-200 ring-1 ring-blue-100' 
                    : 'bg-white border-gray-200 hover:border-blue-300 hover:shadow-md cursor-pointer'
                }`}
                onClick={() => !isCurrentClip && onClipSelect(match)}
              >
                <div className={`absolute top-0 left-0 w-1 h-full ${
                  isCurrentClip ? 'bg-blue-500' : 'bg-gray-200 group-hover:bg-blue-300 transition-colors'
                }`} />
                
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <div className={`w-6 h-6 rounded-md flex items-center justify-center text-xs font-bold ${
                      isCurrentClip 
                        ? 'bg-blue-100 text-blue-600' 
                        : 'bg-gray-100 text-gray-500 group-hover:bg-blue-50 group-hover:text-blue-600 transition-colors'
                    }`}>
                      {matchAbsoluteIndex}
                    </div>
                    {isCurrentClip && (
                      <span className="text-xs font-medium text-blue-700 bg-blue-50 px-2 py-0.5 rounded-full">
                        Current Clip
                      </span>
                    )}
                  </div>
                  <div className={`text-xs font-mono px-2 py-1 rounded border ${
                    isCurrentClip 
                      ? 'bg-gray-100 text-gray-600 border-gray-200' 
                      : 'bg-gray-100 text-gray-600 group-hover:bg-blue-50 group-hover:text-blue-700 transition-colors'
                  }`}>
                    {formatTimestamp(match.timestamp_start)} - {formatTimestamp(match.timestamp_end)}
                  </div>
                </div>

                {match.clip_text && (
                  <div className={`flex items-start gap-3 text-sm ${
                    isCurrentClip 
                      ? 'text-gray-700 bg-gray-50/80 p-3 rounded-lg border border-gray-100' 
                      : 'text-gray-600 pl-2'
                  }`}>
                    <MessageSquare size={16} className={`mt-0.5 flex-shrink-0 ${
                      isCurrentClip 
                        ? 'text-blue-400' 
                        : 'text-gray-300 group-hover:text-blue-300 transition-colors'
                    }`} />
                    <p className={isCurrentClip ? 'leading-relaxed' : 'line-clamp-2 group-hover:text-gray-900 transition-colors'}>
                      {match.clip_text}
                    </p>
                  </div>
                )}
                
                {!isCurrentClip && (
                  <div className="absolute right-4 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <ChevronRight size={20} className="text-blue-400" />
                  </div>
                )}
              </div>
            );
          })}
        </div>

      </div>
    </div>
  );
};

export default VideoPlayerMarengo3;
