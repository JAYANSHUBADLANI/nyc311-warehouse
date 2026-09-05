# Does a close timestamp mean the request is closed?

The warehouse defines `is_closed` as the presence of a close timestamp. That is the only definition the duration measures can use, because a duration needs two timestamps and a status string is not one of them. The source also publishes its own status field, and this report measures where the two disagree.

It exists to settle a question the README previously left open: DOB closing 100% of its requests, and EDC closing 1.9%, both looked like artefacts rather than operational facts.

## Citywide

| Close timestamp present | Source status is Closed | Requests | Share |
| --- | --- | --- | --- |
| no | no | 188,846 | 4.85% |
| no | yes | 15 | 0.00% |
| yes | no | 22,288 | 0.57% |
| yes | yes | 3,678,853 | 94.57% |

The disagreement is small citywide and it runs almost entirely one way: requests that carry a close timestamp while the source still calls them something other than Closed.

## Where the disagreement lives

| Agency | Closed by timestamp, not by status | Mean days | Share of agency |
| --- | --- | --- | --- |
| DOB | 17,568 | 12.19 | 15.11% |
| DOT | 3,319 | 0.44 | 1.22% |
| DEP | 1,218 | 2.81 | 0.57% |
| NYPD | 119 | 0.01 | 0.01% |
| DOHMH | 39 | 10.79 | 0.05% |
| DHS | 12 | 79.06 | 0.02% |
| DPR | 5 | 26.91 | 0.00% |
| HPD | 5 | 6.68 | 0.00% |
| DSNY | 3 | 0.00 | 0.00% |

## DOB and EDC in detail

| Agency | Source status | Requests | With a close timestamp |
| --- | --- | --- | --- |
| DOB | Closed | 98,719 | 98,719 |
| DOB | Open | 10,879 | 10,879 |
| DOB | Assigned | 6,689 | 6,689 |
| EDC | In Progress | 13,992 | 0 |
| EDC | Closed | 268 | 268 |

## The answer

**DOB's 100% closure rate is an artefact of the definition.** DOB populates a close timestamp on 17,568 requests whose own status still reads Open or Assigned. Those requests satisfy `is_closed` and there is nothing wrong with the warehouse, but the number does not mean what a reader would take it to mean. Scored on the source's status field instead, DOB closes 84.9% of 116,287 requests, not 100%.

**EDC's 1.9% is not an artefact.** EDC's open requests carry no close timestamp and the source status agrees with that: they sit at In Progress. This is a genuine absence of recorded closures rather than a definitional disagreement, so it is either a real backlog or an agency that does not record closure in this system. The data cannot separate those two, and this report does not claim to.

Both agencies should still be kept out of cross agency comparison, but for different reasons, and only one of them is a measurement problem.
