/* nbd client library in userspace: state machine
 * Copyright Red Hat
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
 */

#include <assert.h>
#include <stddef.h>

#define ASSERT_MEMBER_ALIAS(type, member_a, member_b) \
  STATIC_ASSERT (offsetof (type, member_a) == offsetof (type, member_b) && \
                 sizeof ((type *)NULL)->member_a == \
                 sizeof ((type *)NULL)->member_b, member_alias)

/* State machine for receiving reply messages from the server.
 *
 * Note that we never block while in this sub-group. If there is
 * insufficient data to finish parsing a reply, requiring us to block
 * until POLLIN, we instead track where in the state machine we left
 * off, then return to READY to actually block. Then, on entry to
 * REPLY.START, we can tell if this is the start of a new reply (rlen
 * is 0, stay put), a continuation of the preamble (reply_state is
 * STATE_START, resume with RECV_REPLY), or a continuation from any
 * other location (reply_state contains the state to jump to).
 */

static void
save_reply_state (struct nbd_handle *h)
{
  assert (h->rlen);
  assert (h->reply_state == STATE_START);
  h->reply_state = get_next_state (h);
  assert (h->reply_state != STATE_START);
}

STATE_MACHINE {
 REPLY.START:
  /* If rlen is non-zero, we are resuming an earlier reply cycle. */
  if (h->rlen > 0) {
    if (h->reply_state != STATE_START) {
      assert (nbd_internal_is_state_processing (h->reply_state));
      SET_NEXT_STATE (h->reply_state);
      h->reply_state = STATE_START;
    }
    else
      SET_NEXT_STATE (%RECV_REPLY);
    return 0;
  }

  /* This state is entered when a read notification is received in the
   * READY state.  Therefore we know the socket is readable here.
   * Reading a zero length now would indicate that the socket has been
   * closed by the server and so we should jump to the CLOSED state.
   * However recv_into_rbuf will fail in this case, so test it as a
   * special case.
   */
  ssize_t r;

  /* With extended headers, there is only one size to read, so we can
   * do it all in one syscall.  But for older structured replies, we
   * don't know if we have a simple or structured reply until we read
   * the magic number, requiring a two-part read with
   * CHECK_REPLY_MAGIC below.  This works because the structured_reply
   * header is larger, and because the last member of a simple reply,
   * cookie, is coincident between all three structs (intentional
   * design decisions in the NBD spec when structured and extended
   * replies were added).
   */
  ASSERT_MEMBER_ALIAS (union reply_header, simple.magic, magic);
  ASSERT_MEMBER_ALIAS (union reply_header, simple.cookie, cookie);
  ASSERT_MEMBER_ALIAS (union reply_header, structured.magic, magic);
  ASSERT_MEMBER_ALIAS (union reply_header, structured.cookie, cookie);
  ASSERT_MEMBER_ALIAS (union reply_header, extended.magic, magic);
  ASSERT_MEMBER_ALIAS (union reply_header, extended.cookie, cookie);
  assert (h->reply_cmd == NULL);
  assert (h->rlen == 0);

  h->rbuf = &h->sbuf.reply.hdr;
  if (h->extended_headers)
    h->rlen = sizeof h->sbuf.reply.hdr.extended;
  else
    h->rlen = sizeof h->sbuf.reply.hdr.simple;

  r = h->sock->ops->recv (h, h->sock, h->rbuf, h->rlen);
  if (r == -1) {
    /* In theory this should never happen because when we enter this
     * state we should have notification that the socket is ready to
     * read.  However it can in fact happen when using TLS in
     * conjunction with a slow, remote server.  If it does happen,
     * ignore it - we will reenter this same state again next time the
     * socket is ready to read.
     */
    if (errno == EAGAIN || errno == EWOULDBLOCK)
      return 0;

    /* sock->ops->recv called set_error already. */
    SET_NEXT_STATE (%.DEAD);
    return 0;
  }
  if (r == 0) {
    SET_NEXT_STATE (%.CLOSED);
    return 0;
  }
#ifdef DUMP_PACKETS
  nbd_internal_hexdump (h->rbuf, r, stderr);
#endif

  h->bytes_received += r;
  h->rbuf = (char *)h->rbuf + r;
  h->rlen -= r;
  SET_NEXT_STATE (%RECV_REPLY);
  return 0;

 REPLY.RECV_REPLY:
  switch (recv_into_rbuf (h)) {
  case -1: SET_NEXT_STATE (%.DEAD); return 0;
  case 1: SET_NEXT_STATE (%.READY);
    /* Special case: if we have a short read, but got at least far
     * enough to decode the magic number, we can check if the server
     * is matching our expectations. This lets us avoid deadlocking if
     * we are blocked waiting for a 32-byte extended reply, while a
     * buggy server only sent a shorter simple or structured reply.
     * Magic number checks here must be repeated in CHECK_REPLY_MAGIC,
     * since we do not always encounter a short read.
     */
    if (h->extended_headers &&
        (char *)h->rbuf >=
        (char *)&h->sbuf.reply.hdr + sizeof h->sbuf.reply.hdr.magic) {
      uint32_t magic = be32toh (h->sbuf.reply.hdr.magic);
      if (magic != NBD_EXTENDED_REPLY_MAGIC) {
        SET_NEXT_STATE (%.DEAD); /* We've probably lost synchronization. */
        set_error (0, "invalid or unexpected reply magic 0x%" PRIx32, magic);
      }
    }
    return 0;
  case 0: SET_NEXT_STATE (%CHECK_REPLY_MAGIC);
  }
  return 0;

 REPLY.CHECK_REPLY_MAGIC:
  struct command *cmd;
  uint32_t magic;
  uint64_t cookie;

  magic = be32toh (h->sbuf.reply.hdr.magic);
  switch (magic) {
  case NBD_SIMPLE_REPLY_MAGIC:
    if (h->extended_headers)
      /* Server is non-compliant, and we've already read more bytes
       * than a simple header contains; no recovery possible
       */
      goto invalid;

    /* All other payload checks handled in the simple payload engine */
    SET_NEXT_STATE (%SIMPLE_REPLY.START);
    break;

  case NBD_STRUCTURED_REPLY_MAGIC:
    if (h->extended_headers)
      /* Server is non-compliant, and we've already read more bytes
       * than a structured header contains; no recovery possible
       */
      goto invalid;

    /* We've only read the bytes that fill hdr.simple.  But
     * hdr.structured is longer, so prepare to read the remaining
     * bytes.  We depend on the memory aliasing in union sbuf to
     * overlay the two reply types.
     */
    STATIC_ASSERT (sizeof h->sbuf.reply.hdr.simple ==
                   offsetof (struct nbd_structured_reply, length),
                   simple_structured_overlap);
    assert (h->rbuf == (char *)&h->sbuf + sizeof h->sbuf.reply.hdr.simple);
    h->rlen = sizeof h->sbuf.reply.hdr.structured;
    h->rlen -= sizeof h->sbuf.reply.hdr.simple;
    SET_NEXT_STATE (%RECV_STRUCTURED_REMAINING);
    break;

  case NBD_EXTENDED_REPLY_MAGIC:
    if (!h->extended_headers)
      /* Server is non-compliant.  We could continue reading bytes up
       * to the length of an extended reply to regain sync, but old
       * servers are unlikely to send this magic, so it's just as easy
       * to punt.
       */
      goto invalid;

    /* All other payload checks handled in the chunk payload engine */
    SET_NEXT_STATE (%CHUNK_REPLY.START);
    break;

  default:
    goto invalid;
  }

  /* NB: This works for all three reply types, even though we haven't
   * finished reading a structured header yet, because the cookie is
   * stored at the same offset.  See the ASSERT_MEMBER_ALIAS above in
   * state REPLY.START that confirmed this.
   */
  h->chunks_received++;
  cookie = be64toh (h->sbuf.reply.hdr.cookie);
  /* Find the command amongst the commands in flight. If the server sends
   * a reply for an unknown cookie, FINISH will diagnose that later.
   */
  for (cmd = h->cmds_in_flight; cmd != NULL; cmd = cmd->next) {
    if (cmd->cookie == cookie)
      break;
  }
  h->reply_cmd = cmd;
  return 0;

 invalid:
  SET_NEXT_STATE (%.DEAD); /* We've probably lost synchronization. */
  set_error (0, "invalid or unexpected reply magic 0x%" PRIx32, magic);
#if 0 /* uncomment to see desynchronized data */
  nbd_internal_hexdump (&h->sbuf.reply.hdr.simple,
                        sizeof (h->sbuf.reply.hdr.simple),
                        stderr);
#endif
  return 0;

 REPLY.RECV_STRUCTURED_REMAINING:
  switch (recv_into_rbuf (h)) {
  case -1: SET_NEXT_STATE (%.DEAD); return 0;
  case 1:
    save_reply_state (h);
    SET_NEXT_STATE (%.READY);
    return 0;
  case 0: SET_NEXT_STATE (%CHUNK_REPLY.START);
  }
  return 0;

 REPLY.FINISH_COMMAND:
  struct command *prev_cmd, *cmd;
  uint64_t cookie;
  bool retire;

  /* NB: This works for both simple and structured replies because the
   * handle (our cookie) is stored at the same offset.  See the
   * STATIC_ASSERT above in state REPLY.START that confirmed this.
   */
  cookie = be64toh (h->sbuf.reply.hdr.cookie);
  /* Find the command amongst the commands in flight. */
  for (cmd = h->cmds_in_flight, prev_cmd = NULL;
       cmd != NULL;
       prev_cmd = cmd, cmd = cmd->next) {
    if (cmd->cookie == cookie)
      break;
  }
  assert (h->reply_cmd == cmd);
  if (cmd == NULL) {
    debug (h, "skipped reply for unexpected cookie %" PRIu64
           ", this is probably a bug in the server", cookie);
    SET_NEXT_STATE (%.READY);
    return 0;
  }

  retire = cmd->type == NBD_CMD_DISC;
  h->reply_cmd = NULL;

  /* Notify the user */
  if (CALLBACK_IS_NOT_NULL (cmd->cb.completion)) {
    int error = cmd->error;
    int r;

    assert (cmd->type != NBD_CMD_DISC);
    r = CALL_CALLBACK (cmd->cb.completion, &error);
    switch (r) {
    case -1:
      if (error)
        cmd->error = error;
      break;
    case 1:
      retire = true;
      break;
    }
  }

  /* Move it to the end of the cmds_done list. */
  if (prev_cmd != NULL)
    prev_cmd->next = cmd->next;
  else
    h->cmds_in_flight = cmd->next;
  cmd->next = NULL;
  if (retire)
    nbd_internal_retire_and_free_command (cmd);
  else {
    if (h->cmds_done_tail != NULL)
      h->cmds_done_tail = h->cmds_done_tail->next = cmd;
    else {
      assert (h->cmds_done == NULL);
      h->cmds_done = h->cmds_done_tail = cmd;
    }
  }
  h->in_flight--;
  assert (h->in_flight >= 0);

  SET_NEXT_STATE (%.READY);
  return 0;

} /* END STATE MACHINE */
