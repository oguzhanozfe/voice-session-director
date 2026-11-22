# Plan a voice session

A booth supervisor has fixed windows for two performers and one actor who is unavailable. Upload the script log and the session windows to find a workable order and an explicit list of lines that did not fit.

Times are minutes after midnight for one production day. Window IDs and line IDs must be unique. Every line specifies a performer, scene and text, with optional take count and pickup flag. Global settings control words per minute, setup for a new scene and reset time between takes. The planner estimates speaking time from word count, accounts for every take, and reserves setup time at the beginning of a window and when switching scenes. It schedules eligible pickups first, then minimizes setup and preserves original script order on ties. Oversized lines do not block shorter ones.

Approve slots to create `booth-schedule.csv` with exact start/end times and the script. Removing a proposed slot leaves its time free. Other booked slots retain their times for coordination with performers. The duration model does not account for acting beats, retakes beyond the estimate, or performer-specific speech rates.
