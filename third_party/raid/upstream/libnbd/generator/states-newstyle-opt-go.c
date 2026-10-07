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

/* State machine for ending fixed newstyle handshake with NBD_OPT_GO. */

STATE_MACHINE {
 NEWSTYLE.OPT_GO.START:
  uint16_t nrinfos = 0;

  nbd_internal_reset_size_and_flags (h);
  if (h->request_block_size)
    nrinfos++;
  if (h->full_info)
    nrinfos += 2;

  assert (h->gflags & LIBNBD_HANDSHAKE_FLAG_FIXED_NEWSTYLE);
  if (h->opt_current == NBD_OPT_INFO)
    assert (h->opt_mode);
  else if (!h->opt_current) {
    assert (!h->opt_mode);
    assert (CALLBACK_IS_NULL (h->opt_cb.completion));
    h->opt_current = NBD_OPT_GO;
  }
  h->sbuf.option.version = htobe64 (NBD_NEW_VERSION);
  h->sbuf.option.option = htobe32 (h->opt_current);
  h->sbuf.option.optlen =
    htobe32 (/* exportnamelen */ 4 + strlen (h->export_name)
             + sizeof nrinfos + 2 * nrinfos);
  h->chunks_sent++;
  h->wbuf = &h->sbuf;
  h->wlen = sizeof h->sbuf.option;
  h->wflags = MSG_MORE;
  SET_NEXT_STATE (%SEND);
  return 0;

 NEWSTYLE.OPT_GO.SEND:
  const uint32_t exportnamelen = strlen (h->export_name);

  switch (send_from_wbuf (h)) {
  case -1: SET_NEXT_STATE (%.DEAD); return 0;
  case 0:
    h->sbuf.len = htobe32 (exportnamelen);
    h->wbuf = &h->sbuf;
    h->wlen = 4;
    h->wflags = MSG_MORE;
    SET_NEXT_STATE (%SEND_EXPORTNAMELEN);
  }
  return 0;

 NEWSTYLE.OPT_GO.SEND_EXPORTNAMELEN:
  switch (send_from_wbuf (h)) {
  case -1: SET_NEXT_STATE (%.DEAD); return 0;
  case 0:
    h->wbuf = h->export_name;
    h->wlen = strlen (h->export_name);
    h->wflags = MSG_MORE;
    SET_NEXT_STATE (%SEND_EXPORT);
  }
  return 0;

 NEWSTYLE.OPT_GO.SEND_EXPORT:
  uint16_t nrinfos = 0;

  if (h->request_block_size)
    nrinfos++;
  if (h->full_info)
    nrinfos += 2;

  switch (send_from_wbuf (h)) {
  case -1: SET_NEXT_STATE (%.DEAD); return 0;
  case 0:
    h->sbuf.nrinfos = htobe16 (nrinfos);
    h->wbuf = &h->sbuf;
    h->wlen = sizeof h->sbuf.nrinfos;
    SET_NEXT_STATE (%SEND_NRINFOS);
  }
  return 0;

 NEWSTYLE.OPT_GO.SEND_NRINFOS:
  uint16_t nrinfos = 0;

  switch (send_from_wbuf (h)) {
  case -1: SET_NEXT_STATE (%.DEAD); return 0;
  case 0:
    if (h->request_block_size)
      h->sbuf.info[nrinfos++] = htobe16 (NBD_INFO_BLOCK_SIZE);
    if (h->full_info) {
      h->sbuf.info[nrinfos++] = htobe16 (NBD_INFO_NAME);
      h->sbuf.info[nrinfos++] = htobe16 (NBD_INFO_DESCRIPTION);
    }
    h->wbuf = &h->sbuf;
    h->wlen = sizeof h->sbuf.info[0] * nrinfos;
    SET_NEXT_STATE (%SEND_INFO);
  }
  return 0;

 NEWSTYLE.OPT_GO.SEND_INFO:
  switch (send_from_wbuf (h)) {
  case -1: SET_NEXT_STATE (%.DEAD); return 0;
  case 0:
    h->rbuf = &h->sbuf;
    h->rlen = sizeof h->sbuf.or.option_reply;
    SET_NEXT_STATE (%RECV_REPLY);
  }
  return 0;

 NEWSTYLE.OPT_GO.RECV_REPLY:
  switch (recv_into_rbuf (h)) {
  case -1: SET_NEXT_STATE (%.DEAD); return 0;
  case 0:
    if (prepare_for_reply_payload (h, h->opt_current) == -1) {
      SET_NEXT_STATE (%.DEAD);
      return 0;
    }
    SET_NEXT_STATE (%RECV_REPLY_PAYLOAD);
  }
  return 0;

 NEWSTYLE.OPT_GO.RECV_REPLY_PAYLOAD:
  switch (recv_into_rbuf (h)) {
  case -1: SET_NEXT_STATE (%.DEAD); return 0;
  case 0:  SET_NEXT_STATE (%CHECK_REPLY);
  }
  return 0;

 NEWSTYLE.OPT_GO.CHECK_REPLY:
  uint32_t reply;
  uint32_t len;
  const size_t maxpayload = sizeof h->sbuf.or.payload;
  int err;

  reply = be32toh (h->sbuf.or.option_reply.reply);
  len = be32toh (h->sbuf.or.option_reply.replylen);

  switch (reply) {
  case NBD_REP_INFO:
    if (len > maxpayload) {
      /* See prepare_for_reply_payload, used in RECV_REPLY */
      assert (h->rbuf == NULL);
      debug (h, "skipping large NBD_REP_INFO");
    }
    else {
      uint16_t info;
      uint64_t exportsize;
      uint16_t eflags;
      uint32_t min, pref, max;

      assert (len >= sizeof h->sbuf.or.payload.export.info);
      info = be16toh (h->sbuf.or.payload.export.info);
      switch (info) {
      case NBD_INFO_EXPORT:
        if (len != sizeof h->sbuf.or.payload.export) {
          SET_NEXT_STATE (%.DEAD);
          set_error (0, "handshake: incorrect NBD_INFO_EXPORT option reply "
                     "length");
          return 0;
        }
        exportsize = be64toh (h->sbuf.or.payload.export.exportsize);
        eflags = be16toh (h->sbuf.or.payload.export.eflags);
        if (nbd_internal_set_size_and_flags (h, exportsize, eflags) == -1) {
          SET_NEXT_STATE (%.DEAD);
          return 0;
        }
        break;
      case NBD_INFO_BLOCK_SIZE:
        if (len != sizeof h->sbuf.or.payload.block_size) {
          SET_NEXT_STATE (%.DEAD);
          set_error (0, "handshake: incorrect NBD_INFO_BLOCK_SIZE option "
                     "reply length");
          return 0;
        }
        min = be32toh (h->sbuf.or.payload.block_size.minimum);
        pref = be32toh (h->sbuf.or.payload.block_size.preferred);
        max = be32toh (h->sbuf.or.payload.block_size.maximum);
        if (nbd_internal_set_block_size (h, min, pref, max) == -1) {
          SET_NEXT_STATE (%.DEAD);
          return 0;
        }
        break;
      case NBD_INFO_NAME:
        if (len > sizeof h->sbuf.or.payload.name_desc.info + NBD_MAX_STRING ||
            len < sizeof h->sbuf.or.payload.name_desc.info) {
          SET_NEXT_STATE (%.DEAD);
          set_error (0, "handshake: incorrect NBD_INFO_NAME option reply "
                     "length");
          return 0;
        }
        free (h->canonical_name);
        h->canonical_name = strndup (h->sbuf.or.payload.name_desc.str, len - 2);
        if (h->canonical_name == NULL) {
          SET_NEXT_STATE (%.DEAD);
          set_error (errno, "strndup");
          return 0;
        }
        break;
      case NBD_INFO_DESCRIPTION:
        if (len > sizeof h->sbuf.or.payload.name_desc.info + NBD_MAX_STRING ||
            len < sizeof h->sbuf.or.payload.name_desc.info) {
          SET_NEXT_STATE (%.DEAD);
          set_error (0, "handshake: incorrect NBD_INFO_DESCRIPTION option "
                     "reply length");
          return 0;
        }
        free (h->description);
        h->description = strndup (h->sbuf.or.payload.name_desc.str, len - 2);
        if (h->description == NULL) {
          SET_NEXT_STATE (%.DEAD);
          set_error (errno, "strndup");
          return 0;
        }
        break;
      default:
        debug (h, "skipping unknown NBD_REP_INFO type %d",
               be16toh (h->sbuf.or.payload.export.info));
        break;
      }
    }
    /* Server is allowed to send any number of NBD_REP_INFO, read next one. */
    h->rbuf = &h->sbuf;
    h->rlen = sizeof (h->sbuf.or.option_reply);
    SET_NEXT_STATE (%RECV_REPLY);
    return 0;
  case NBD_REP_ERR_UNSUP:
    if (h->opt_current == NBD_OPT_GO) {
      debug (h, "server is confused by NBD_OPT_GO, continuing anyway");
      SET_NEXT_STATE (%^OPT_EXPORT_NAME.START);
      return 0;
    }
    /* fallthrough */
  default:
    if (handle_reply_error (h) == -1) {
      SET_NEXT_STATE (%.DEAD);
      return 0;
    }
    if (reply == NBD_REP_ERR_UNSUP)
      assert (h->opt_current == NBD_OPT_INFO);

    nbd_internal_reset_size_and_flags (h);
    h->meta_valid = false;
    err = nbd_get_errno () ? : ENOTSUP;
    break;
  case NBD_REP_ACK:
    nbd_internal_set_payload (h);
    err = 0;
    break;
  }

  if (err == 0 && h->opt_current == NBD_OPT_GO)
    SET_NEXT_STATE (%^FINISHED);
  else if (h->opt_mode)
    SET_NEXT_STATE (%.NEGOTIATING);
  else
    SET_NEXT_STATE (%^PREPARE_OPT_ABORT);
  CALL_CALLBACK (h->opt_cb.completion, &err);
  nbd_internal_free_option (h);
  return 0;

} /* END STATE MACHINE */
