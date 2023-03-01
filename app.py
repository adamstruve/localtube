from flask import Flask, jsonify, request, send_from_directory
import yt_dlp
import sqlite3
import threading
import os.path
from flask_cors import CORS  # import CORS

app = Flask(__name__)
CORS(app)  # enable CORS because lol

# Download the video and thumbnail using yt-dlp. 
def download_video(youtube_url):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': 'videos/%(id)s.%(ext)s',
        'writethumbnail': True,
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4'
        }]
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(youtube_url, download=True)
        video_title = info_dict.get('title', None)
        video_id = info_dict.get('id', None)
        video_filename = ydl.prepare_filename(info_dict)
        thumbnail_url = info_dict['thumbnail']
        thumbnail_extension = os.path.splitext(thumbnail_url)[1]
        
        # extract YouTube ID from video filename
        base_name, ext = os.path.splitext(video_filename)
        video_id = base_name[-11:]
        
        # set video filename to YouTube ID
        video_filename = os.path.join('videos', video_id + ext)
        
    return (video_title, video_id, video_filename, thumbnail_extension)


# Route to handle video download and database storage
@app.route('/download', methods=['POST'])
def download_and_store():
    # Get YouTube URL from request body
    youtube_url = request.json['url']
    
    # Store video information into SQLite database
    conn = sqlite3.connect('videos.db')
    c = conn.cursor()
    c.execute("INSERT INTO videos (url) VALUES (?)", (youtube_url,))
    video_id = c.lastrowid
    conn.commit()
    conn.close()
    
    # Start downloading video and thumbnail in the background
    def download_video_async():
        video_title, video_id, video_filename, thumbnail_extension = download_video(youtube_url)

        # Clean up filename and thumbnail name
        video_filename = video_filename.replace('videos/', '')
        thumbnail_filename = video_id + thumbnail_extension

        conn = sqlite3.connect('videos.db')
        c = conn.cursor()
        c.execute("UPDATE videos SET title=?, filename=?, thumbnail=?, video_id=? WHERE url=?", 
                  (video_title, video_filename, thumbnail_filename, video_id, youtube_url))
        conn.commit()
        conn.close()
    
    threading.Thread(target=download_video_async).start()
    
    return jsonify({'message': 'Video download submitted successfully!'})

@app.route('/videos', methods=['GET'])
def get_videos():
    conn = sqlite3.connect('videos.db')
    c = conn.cursor()
    c.execute("SELECT * FROM videos")
    videos = [dict(id=row[0], title=row[1], filename=row[2], thumbnail=row[3], url=row[4], video_id=row[5]) for row in c.fetchall()]
    conn.close()
    return jsonify(videos)

# Serve the stuff
@app.route('/videos/<path:path>')
def serve_video(path):
    return send_from_directory('videos', path)

@app.route('/video/<int:video_id>', methods=['GET'])
def get_video(video_id):
    conn = sqlite3.connect('videos.db')
    c = conn.cursor()
    c.execute("SELECT * FROM videos WHERE id=?", (video_id,))
    video = c.fetchone()
    conn.close()
    if video is None:
        return jsonify({'error': 'Video not found'}), 404
    else:
        return jsonify({'id': video[0], 'title': video[1], 'filename': video[2], 'thumbnail': video[3], 'url': video[4], 'video_id': video[5]})


# Delete a video
@app.route('/delete', methods=['POST'])
def delete_video():
    # Get video ID from request body
    video_id = request.json['id']

    # Look up video in the database
    conn = sqlite3.connect('videos.db')
    c = conn.cursor()
    c.execute("SELECT * FROM videos WHERE id=?", (video_id,))
    video = c.fetchone()

    if video is None:
        conn.close()
        return jsonify({'error': 'Video not found'}), 404

    # Delete video file and thumbnail
    filename = video[2]
    thumbnail = video[3]
    if filename:
        os.remove(os.path.join('videos', filename))
    if thumbnail:
        os.remove(os.path.join('videos', thumbnail))

    # Delete video from database
    c.execute("DELETE FROM videos WHERE id=?", (video_id,))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Video deleted successfully!'})


if __name__ == '__main__':
    db_file = 'videos.db'
    
    # Create database file and videos table if they don't exist
    if not os.path.exists(db_file):
        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute('''CREATE TABLE videos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT,
                        filename TEXT,
                        thumbnail TEXT,
                        url TEXT,
                        video_id TEXT
                    )''')
        conn.commit()
        conn.close()
    
    app.run(debug=True)
