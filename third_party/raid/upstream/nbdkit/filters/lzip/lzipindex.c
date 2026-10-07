/* nbdkit lzip index
 * Copyright Jan Felix Langenbach
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met:
 *
 * * Redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer.
 *
 * * Redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution.
 *
 * * Neither the name of Red Hat nor the names of its contributors may be
 * used to endorse or promote products derived from this software without
 * specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY RED HAT AND CONTRIBUTORS ''AS IS'' AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
 * THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
 * PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL RED HAT OR
 * CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
 * USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
 * ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
 * OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
 * SUCH DAMAGE.
 */

#include <config.h>

#include <assert.h>
#include <stdlib.h>

#include "vector.h"

#include "lzipindex.h"

int
lzip_index_prepend (lzip_index *index, lzip_index_member const *member)
{
  assert (index);
  assert (member);

  return lzip_index_members_append (&index->members, *member);
}

void
lzip_index_finalize (lzip_index *index)
{
  assert (index);

  uint64_t combined_data_size = 0;
  uint64_t indexable_data_size = 0;

  for (size_t j = 0; j < index->members.len; ++j) {
    size_t i = index->members.len - j - 1;
    lzip_index_member *member = &index->members.ptr[i];

    member->data_offset = combined_data_size;
    combined_data_size += member->data_size;

    if (j == 0) {
      indexable_data_size = member->data_size;
      continue;
    }

    if (i == 0 || indexable_data_size == 0) {
      continue;
    }

    if (member->data_size != indexable_data_size) {
      indexable_data_size = 0;
    }
  }

  index->combined_data_size = combined_data_size;
  index->indexable_data_size = indexable_data_size;
}

static int
comparator (void const *key, lzip_index_member const *member)
{
  uint64_t const *data_offset_ptr = key;
  uint64_t data_offset = *data_offset_ptr;

  if (data_offset < member->data_offset) return +1;
  if (data_offset < member->data_offset + member->data_size) return 0;
  return -1;
}

lzip_index_member const *
lzip_index_search (lzip_index const *index, uint64_t data_offset)
{
  if (!index) return NULL;
  if (data_offset > index->combined_data_size) return NULL;

  if (index->indexable_data_size) {
    size_t member_index = data_offset / index->indexable_data_size;
    return &index->members.ptr[index->members.len - member_index - 1];
  }

  return lzip_index_members_search (&index->members, &data_offset,
                                    comparator);
}

void
lzip_index_destroy (lzip_index *index)
{
  if (!index) return;
  lzip_index_members_reset (&index->members);
  *index = (lzip_index) {};
}
