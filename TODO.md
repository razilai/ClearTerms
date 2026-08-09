# TODO

## security

- whats considered a new document? 1 letter diff? 1 sentence diff?
  - where is this validation handled? (probably db AND services)
- rate limiting for requests per-user (hourly? weekly?)

## database

- should likes be on a separate table or as part of post?
- do comments have likes? should they?
- how does indexing work?
- moving to postgres
- field validation (length, size)

## agent

- validating that we don't insert too big of a string into analysis (python string cap size - enforce in database)
- jailbreaks and hallucinations

## config

- check model name in config/ vs agent/

## misc

- priority queue
- personal todo list
- better forum, integrated with quoting problematic clauses
