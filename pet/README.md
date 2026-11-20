# The pet's window

A small floating window for the pet: a pixel dog that stands in the corner of your screen and is the voice of your
coding agent ([docs/harness.md](../docs/harness.md)).

    cd pet && npm install && npm start

That is all there is to start: the pet runs the call server itself (`jev-interaction serve`, on a free port, with the
hub for coding agents on) and stops it when it quits. Settings and keys live in `~/.jev-interaction/.env`; the first
time, the dog tells you it is not set up and a click opens the setup page. `JEV_PET_SERVER` names another command to
run the server with; `JEV_PET_URL` points the pet at a server that is already running.

Click the dog to start; click again to put it to sleep or wake it (or Cmd/Ctrl+Shift+J from anywhere). Double-click
hangs up. Right-click for the menu. Drag it by the space around it.

Without the window the same pet is at http://localhost:8080/pet in a browser.

| the dog | what is going on |
|---|---|
| stands, blinks | nothing to do |
| ears up | it hears you |
| paw on chin | writing its answer |
| mouth moving | talking |
| struts | a task is running in the coding agent |
| waves, a red ! | the coding agent needs your OK |
| lies down, z z z | asleep: nothing is sent to Jev or to the recognizer until your voice or news wakes it |
