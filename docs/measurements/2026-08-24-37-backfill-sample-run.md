# Vercel-to-harness backfill — outcome report

> **Project names are redacted to stable handles in this committed copy.** This repository ships as a plugin, and a committed file naming live projects in the account would be copied to every install. The full named report is in the run directory, which is git-ignored, and a handle is `p-` plus the first twelve hex of the sha256 of the name.

Inventory converged: two agreeing walks, started 1787598540, completed 1787598548.

| Count | What |
| --- | --- |
| 181 | rows in the snapshot |
| 10 | rows PROCESSED by this run |
| 171 | rows `not_attempted` (sampled out) |
| 0 | rows now **live** on the harness |

## Flagged, by reason

| Reason | Rows |
| --- | --- |
| `harness_fetch_denied` | 2 |
| `mapping_not_found` | 8 |

## Every processed row

| Project | Outcome | Reason |
| --- | --- | --- |
| `p-be5453797142` | flagged | `mapping_not_found` |
| `p-fbea1f5c8b24` | flagged | `mapping_not_found` |
| `p-36eddaab417d` | flagged | `mapping_not_found` |
| `p-422fe94cc605` | flagged | `harness_fetch_denied` |
| `p-7bbd79beba34` | flagged | `mapping_not_found` |
| `p-4e99ea9483ee` | flagged | `mapping_not_found` |
| `p-3eaabc33fb36` | flagged | `mapping_not_found` |
| `p-d2803877c710` | flagged | `mapping_not_found` |
| `p-8d11cf8deb0f` | flagged | `mapping_not_found` |
| `p-0a529aa125da` | flagged | `harness_fetch_denied` |

## Not attempted

These rows were in the snapshot and this run did not touch them. They have NO outcome — not a flag — because no reason in the vocabulary would describe them truthfully. The selection rule was `--limit` over the snapshot in its recorded order.

`p-0ac59a2cef7f`, `p-954fcbf4bd82`, `p-dbac3e420fae`, `p-56e2f70d0d21`, `p-7a5890d7fb50`, `p-6bd2dacff862`, `p-521da5817924`, `p-e7fc8d1582c3`, `p-23c9588cdbcf`, `p-d196431eb1c0`, `p-562dfc9babe5`, `p-b09f64ef1d0a`, `p-fbd54061d684`, `p-eae796b07e46`, `p-624d2eba712f`, `p-9965cf6af835`, `p-a3db4557a28c`, `p-1b9b98035b78`, `p-005fbfc3ed80`, `p-030bda78b3c2`, `p-4277de961f8a`, `p-06b18736d3d4`, `p-8acaf89f5a98`, `p-76a9da734781`, `p-047d2b0bd2de`, `p-e14749d85d85`, `p-31458de6f3b3`, `p-3e61e63782e0`, `p-7909bbc1c27f`, `p-eb8d468011df`, `p-28616a3c155b`, `p-11700e6c189f`, `p-49e72067b780`, `p-3209e6a68eed`, `p-646c846fadb7`, `p-a68baf4b82ac`, `p-30e8dd595756`, `p-7f878b148a9b`, `p-6645e9b7b1b9`, `p-2cf293bc75f8`, `p-bd26acfc1b86`, `p-8539529ff5ea`, `p-9d6f76b5dacc`, `p-b03e5d08f874`, `p-76c0c5697d86`, `p-0350f7a13391`, `p-1cec015ad662`, `p-fc39e641d5ef`, `p-854e6a5fc751`, `p-aafb6fec8e67`, `p-b35b72309321`, `p-d3ee31e5cc45`, `p-d8d30d3e53b0`, `p-35ea205ae466`, `p-99b725a5f940`, `p-84eebc3f6222`, `p-424aa81f2cfa`, `p-160eb02cb99c`, `p-85b0bf9acca4`, `p-374378578065`, `p-8bc8b3edd615`, `p-65d0b2f0e56c`, `p-cdcc3398471d`, `p-150eb41a360c`, `p-f8f2fefa37f8`, `p-b0fcab365788`, `p-0dccbe749771`, `p-72616a99ca94`, `p-8d250b75db51`, `p-7c6ea89b017f`, `p-9c518ff8fc28`, `p-2b33722834a8`, `p-1e5c66c66196`, `p-b796f06c15f8`, `p-b395c827cc92`, `p-baf316e060da`, `p-cb7862ecb0f0`, `p-927a80504412`, `p-856d76d975a9`, `p-a70dcf35f572`, `p-ebe99b8dfed9`, `p-5741ad6b677a`, `p-d6fcb6315876`, `p-34fe023916aa`, `p-f8b62659b639`, `p-f1bf92ea53d8`, `p-4adf94287fac`, `p-5ceb35c321d1`, `p-1a8156d70a41`, `p-953dceb8b8be`, `p-f7aa83003dc3`, `p-5b1aa8209e78`, `p-63a45651f2be`, `p-e2eb6030d93e`, `p-0ad833cf4484`, `p-685fc2e4f3c6`, `p-581a00afd52d`, `p-9d7a9bff24fb`, `p-88e09ff916fd`, `p-8897e15cdde1`, `p-8bc2275de5f5`, `p-37de33fae287`, `p-7c08208614e8`, `p-d5d479f2a2fe`, `p-ac3f6e14b3e3`, `p-4c39b15a6904`, `p-105ba2ec639f`, `p-4012890afdc1`, `p-3655fbf92465`, `p-cd59ab13aa60`, `p-c2517c562ad7`, `p-b72b6db0cacf`, `p-eca4e289d5cc`, `p-053edab140cd`, `p-6e777c1d34f2`, `p-c45739aae0f7`, `p-1147e33238ba`, `p-f6b79a517a3c`, `p-6eaa28c02f85`, `p-e5e6cc6255d8`, `p-13f4b39e7b80`, `p-4b1a3febc23d`, `p-4ad572f025c4`, `p-dfd2800e59ca`, `p-fb8b94c83db0`, `p-eca888cd43ab`, `p-3b1fbf431f1d`, `p-312fc81043c6`, `p-f647e220996f`, `p-862c9217ca02`, `p-4929fef97d6c`, `p-a4fbe1d76051`, `p-c2d289542d74`, `p-7f694af38be7`, `p-d2fef5bc6de4`, `p-e16d3e4d68a1`, `p-f0a6baa01634`, `p-d3202cbca8b8`, `p-4bf3a5ed16d8`, `p-f213ad64544e`, `p-66eeca6d4160`, `p-4c8ddfe1528a`, `p-e61be2f636d7`, `p-c68f9d41af0c`, `p-ec03d8abaf03`, `p-98e4992c6c12`, `p-643651fe36ec`, `p-de40939fd47d`, `p-43e9706fda22`, `p-d47716c0bd08`, `p-901f7d796638`, `p-fbaae4f25774`, `p-e138d96e1db8`, `p-9eb399a3a28a`, `p-670ef009262f`, `p-5c9d751d8a5e`, `p-3d6da5409fea`, `p-3eac51e224cf`, `p-86ea72ca805b`, `p-66ffa7cc6d56`, `p-97203ef6f1c9`, `p-ac6cdd79b7da`, `p-f7ffbbec6ff7`, `p-340ab5b5ff10`, `p-2550d43f03a8`, `p-74997eca710f`, `p-5bfb8cae9e19`, `p-3b0d6562bc5f`, `p-4f13b3a3d959`, `p-4ae48edba0f3`, `p-f53f18e92be4`

