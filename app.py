from flask import Flask, jsonify, request, send_from_directory
import yt_dlp
import sqlite3
import threading
import os.path
import requests
from flask_cors import CORS  # import CORS

app = Flask(__name__)
CORS(app)  # enable CORS because lol

# Download the video and thumbnail using yt-dlp. 
def download_video(youtube_url):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': 'videos/%(id)s.%(ext)s',
        'writethumbnail': False,
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

        # download thumbnail and save with video ID and original extension
        thumbnail_content = requests.get(thumbnail_url).content
        thumbnail_filename = os.path.join('videos', video_id + thumbnail_extension)
        with open(thumbnail_filename, 'wb') as thumbnail_file:
            thumbnail_file.write(thumbnail_content)

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
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('page_size', 10))

    conn = sqlite3.connect('videos.db')
    c = conn.cursor()

    # Count total videos to calculate total pages
    c.execute("SELECT COUNT(*) FROM videos WHERE filename IS NOT NULL")
    total_videos = c.fetchone()[0]
    total_pages = (total_videos + page_size - 1) // page_size

    # Select videos for current page
    offset = (page - 1) * page_size
    c.execute("SELECT * FROM videos WHERE filename IS NOT NULL LIMIT ? OFFSET ?", (page_size, offset))
    videos = [dict(id=row[0], title=row[1], filename=row[2], thumbnail=row[3], url=row[4], video_id=row[5]) for row in c.fetchall()]
    conn.close()

    response = {
        'videos': videos,
        'page': page,
        'page_size': page_size,
        'total_videos': total_videos,
        'total_pages': total_pages,
    }
    return jsonify(response)


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
@app.route('/video/<int:video_id>', methods=['DELETE'])
def delete_video(video_id):
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

# Search
@app.route('/search')
def search():
    # Get the search query
    query = request.args.get('q', '')

    # Get pagination parameters
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('page_size', 10))

    # Connect to database and execute query to get matching videos
    conn = sqlite3.connect('videos.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM videos WHERE title LIKE ?", ('%' + query + '%',))
    total_videos = c.fetchone()[0]
    total_pages = (total_videos + page_size - 1) // page_size
    offset = (page - 1) * page_size
    c.execute("SELECT * FROM videos WHERE title LIKE ? LIMIT ? OFFSET ?", ('%' + query + '%', page_size, offset))
    rows = c.fetchall()
    conn.close()

    # Convert the results to a list of dictionaries
    results = []
    for row in rows:
        result = {'id': row[0], 'title': row[1], 'filename': row[2], 'thumbnail': row[3], 'url': row[4], 'video_id': row[5]}
        results.append(result)

    # Return the results and pagination information as JSON
    response = {
        'videos': results,
        'page': page,
        'page_size': page_size,
        'total_videos': total_videos,
        'total_pages': total_pages,
    }
    return jsonify(response)


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
