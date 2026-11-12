# Compensation and the Saga Pattern

The saga pattern manages failures in long-running workflows that cannot use a single database transaction. Each step that has side effects defines a compensating action that undoes it.

## How compensation works

When a step fails after its retries are exhausted, the workflow engine runs the compensating actions of all previously completed steps in reverse order. For example, if a workflow books a flight and then fails to book a hotel, the engine cancels the flight booking.

## Human in the loop

Agent workflows often pause for human approval before irreversible actions such as sending email or spending money. The engine saves a checkpoint of the workflow state, returns control to the caller, and resumes from the checkpoint once a human answers.
