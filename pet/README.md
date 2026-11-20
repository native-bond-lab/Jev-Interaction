# The pet's window

A small floating window for the pet: a pixel dog that stands in the corner of your screen and is the voice of your
coding agent ([docs/harness.md](../docs/harness.md)).

    jev-interaction serve          # with JEV_HARNESS=1 in .env
    cd pet && npm install && npm start

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
