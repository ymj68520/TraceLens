/*
 * Write a YAFFS image with history, using YAFFS's own code, and read one back.
 *
 * Built against Aleph One's yaffs2 "direct" interface (the real YAFFS core,
 * run in user space); see tools/make_yaffs_history_fixture.sh. YAFFS is
 * GPL-2.0; this program is only run to make and check test images and is not
 * part of qnxprobe.
 *
 * The flash is a file holding each page's data then its spare, driven below
 * with NAND programming semantics: a write can only clear bits, so rewriting
 * a spare with 0xFF everywhere but one byte changes only that byte, which is
 * how YAFFS1 marks a chunk deleted.
 *
 *   yaffs_history yaffs2|yaffs1 write IMAGE     make IMAGE and write the history
 *                                               into it, then exit without
 *                                               unmounting, so no checkpoint is
 *                                               written, as on a device imaged
 *                                               while it ran
 *   yaffs_history yaffs2|yaffs1 dump IMAGE OUT  mount IMAGE read-only, skipping
 *                                               any checkpoint so the flash is
 *                                               scanned, and write every file
 *                                               YAFFS reads back under OUT/files
 *                                               and "mode size mtime path" for
 *                                               every entry to OUT/listing
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include "yaffsfs.h"
#include "yaffs_guts.h"

unsigned yaffs_trace_mask = 0;

static int nand_fd = -1;
static int page_data, page_spare, pages_per_block, n_blocks;

static long page_at(int chunk) { return (long)chunk * (page_data + page_spare); }

static int prog(long at, const u8 *buf, int len)
{
	u8 old[4096];
	int i;
	if (pread(nand_fd, old, len, at) != len)
		return YAFFS_FAIL;
	for (i = 0; i < len; i++)
		old[i] &= buf[i];              /* NAND: a write only clears bits */
	return pwrite(nand_fd, old, len, at) == len ? YAFFS_OK : YAFFS_FAIL;
}

/* A YAFFS1 power cut, armed near the end of the history. When garbage
 * collection copies a live chunk it reads the old tags and gives the copy
 * serial + 1 (core/yaffs_guts.c yaffs_gc_process_chunk), and it does not mark
 * the original deleted: the original's block is about to be erased. So the cut
 * is taken just before erasing a block that still holds a live data chunk whose
 * copy, with serial exactly one more, has been written since arming, later on
 * the flash than the original. Two live copies then remain, the older found
 * first by a scan, so only their serial numbers put the newer one in use. (An ordinary
 * rewrite does not reliably increment the serial: with one chunk per tnode
 * group, yaffs_find_chunk_in_group returns without reading the tags it was
 * asked for.) */
static int cut_armed, n_copies, cut_on_mark;
static struct { int obj, chunk, serial, page; } copies[8192];

static void tags1(const u8 *spare, int *obj, int *chunk, int *serial, int *live)
{
	u32 w0 = spare[0] | spare[1] << 8 | spare[2] << 16 | (u32)spare[3] << 24;
	u32 w1 = spare[6] | spare[7] << 8 | spare[11] << 16 | (u32)spare[12] << 24;
	*chunk = w0 & 0xFFFFF;
	*serial = (w0 >> 20) & 3;
	*obj = w1 & 0x3FFFF;
	*live = __builtin_popcount(spare[4]) >= 7 && w0 != 0xFFFFFFFF;
}

static int drv_write(struct yaffs_dev *dev, int chunk, const u8 *data, int data_len,
		     const u8 *oob, int oob_len)
{
	(void)dev;
	if (cut_armed && data && oob && oob_len == 16 && n_copies < 8192) {
		int live;
		tags1(oob, &copies[n_copies].obj, &copies[n_copies].chunk,
		      &copies[n_copies].serial, &live);
		copies[n_copies].page = chunk;
		n_copies++;
	}
	/* The rewrite cut: at a spare-only write (a deletion mark) aimed at a
	 * chunk whose replacement, serial exactly one more, was just written. */
	if (cut_on_mark && !data && oob && oob_len == 16 && n_copies) {
		u8 cur[16];
		int o, c, sr, live;
		if (pread(nand_fd, cur, 16, page_at(chunk) + page_data) == 16) {
			tags1(cur, &o, &c, &sr, &live);
			if (o == copies[n_copies - 1].obj && c == copies[n_copies - 1].chunk &&
			    c > 0 && copies[n_copies - 1].serial == ((sr + 1) & 3))
				_exit(0);
		}
	}
	if (data && prog(page_at(chunk), data, data_len) != YAFFS_OK)
		return YAFFS_FAIL;
	if (oob && prog(page_at(chunk) + page_data, oob, oob_len) != YAFFS_OK)
		return YAFFS_FAIL;
	return YAFFS_OK;
}

static void maybe_cut(int block)
{
	int p, i;
	for (p = 0; cut_armed && p < pages_per_block; p++) {
		u8 sp[16];
		int o, c, sr, live;
		if (pread(nand_fd, sp, 16, page_at(block * pages_per_block + p) + page_data) != 16)
			continue;
		tags1(sp, &o, &c, &sr, &live);
		if (!live || c == 0)
			continue;
		for (i = 0; i < n_copies; i++)
			if (copies[i].obj == o && copies[i].chunk == c &&
			    copies[i].serial == ((sr + 1) & 3) &&
			    copies[i].page > block * pages_per_block + p)
				_exit(0);
	}
}

static int drv_read(struct yaffs_dev *dev, int chunk, u8 *data, int data_len,
		    u8 *oob, int oob_len, enum yaffs_ecc_result *ecc)
{
	(void)dev;
	if (data && pread(nand_fd, data, data_len, page_at(chunk)) != data_len)
		return YAFFS_FAIL;
	if (oob && pread(nand_fd, oob, oob_len, page_at(chunk) + page_data) != oob_len)
		return YAFFS_FAIL;
	if (ecc)
		*ecc = YAFFS_ECC_RESULT_NO_ERROR;
	return YAFFS_OK;
}

static int drv_erase(struct yaffs_dev *dev, int block)
{
	static u8 ff[4096 + 256];
	int p, len = page_data + page_spare;
	(void)dev;
	if (cut_armed)
		maybe_cut(block);
	memset(ff, 0xff, sizeof ff);
	for (p = 0; p < pages_per_block; p++)
		if (pwrite(nand_fd, ff, len, page_at(block * pages_per_block + p)) != len)
			return YAFFS_FAIL;
	return YAFFS_OK;
}

static int drv_ok(struct yaffs_dev *dev, int block) { (void)dev; (void)block; return YAFFS_OK; }
static int drv_init(struct yaffs_dev *dev) { (void)dev; return YAFFS_OK; }

static int is_yaffs2, grouped;

int yaffs_start_up(void)
{
	struct yaffs_dev *dev = calloc(1, sizeof(*dev));
	dev->param.name = strdup("yflash");
	dev->drv.drv_write_chunk_fn = drv_write;
	dev->drv.drv_read_chunk_fn = drv_read;
	dev->drv.drv_erase_fn = drv_erase;
	dev->drv.drv_mark_bad_fn = drv_ok;
	dev->drv.drv_check_bad_fn = drv_ok;
	dev->drv.drv_initialise_fn = drv_init;
	dev->param.total_bytes_per_chunk = page_data;
	dev->param.chunks_per_block = pages_per_block;
	dev->param.start_block = 0;
	dev->param.end_block = n_blocks - 1;
	dev->param.is_yaffs2 = is_yaffs2;
	dev->param.use_nand_ecc = is_yaffs2;   /* YAFFS1 keeps its own data ECC in the spare */
	dev->param.n_reserved_blocks = 5;
	dev->param.n_caches = 10;
	dev->param.wide_tnodes_disabled = grouped;
	yaffsfs_OSInitialisation();
	yaffs_add_device(dev);
	return 0;
}

#define M "/yflash"

static void text(char *buf, int n, const char *tag, int seed)
{
	int i = 0;
	while (i < n) {
		char line[80];
		int l = snprintf(line, sizeof line, "%s line %06d of the yaffs history fixture\n",
				 tag, seed++);
		int take = l < n - i ? l : n - i;
		memcpy(buf + i, line, take);
		i += take;
	}
}

static void put(const char *path, int size, const char *tag)
{
	char *buf = malloc(size + 1);
	int fd = yaffs_open(path, O_CREAT | O_TRUNC | O_RDWR, S_IREAD | S_IWRITE);
	text(buf, size, tag, 0);
	if (fd < 0 || yaffs_write(fd, buf, size) != size) {
		fprintf(stderr, "write %s failed\n", path);
		exit(1);
	}
	yaffs_close(fd);
	free(buf);
}

static void pw(const char *path, long off, int size, const char *tag)
{
	char *buf = malloc(size);
	int fd = yaffs_open(path, O_CREAT | O_RDWR, S_IREAD | S_IWRITE);
	text(buf, size, tag, 500);
	if (fd < 0 || yaffs_pwrite(fd, buf, size, off) != size) {
		fprintf(stderr, "pwrite %s failed\n", path);
		exit(1);
	}
	yaffs_close(fd);
	free(buf);
}

static int do_write(void)
{
	char name[128], *buf;
	int i, round, fd, churn = is_yaffs2 ? 600000 : 250000;
	if (yaffs_mount(M) < 0) {
		fprintf(stderr, "mount failed\n");
		return 1;
	}
	yaffs_mkdir(M "/docs", 0755);
	yaffs_mkdir(M "/docs/sub", 0700);
	yaffs_mkdir(M "/gone", 0755);
	put(M "/keep.txt", 10000, "keep");
	put(M "/docs/big.bin", 300000, "big");
	put(M "/docs/shrunk.bin", 50000, "shrunk");
	put(M "/docs/gap.bin", 50000, "stale");
	put(M "/gone/deleted.txt", 30000, "deleted");
	put(M "/old_name.txt", 5000, "renamed");
	put(M "/docs/sub/linked.txt", 4000, "linked");
	for (i = 0; i < 40; i++) {
		snprintf(name, sizeof name, M "/docs/small_%02d.txt", i);
		put(name, 100 + i * 37, "small");
	}
	/* Newer versions of existing chunks, and data past the old end. */
	pw(M "/docs/big.bin", 100000, 9000, "overwrite");
	pw(M "/keep.txt", 10000, 3000, "append");
	/* A shrink, then a truncate that asks to grow the file again. */
	yaffs_truncate(M "/docs/shrunk.bin", 7000);
	yaffs_truncate(M "/docs/shrunk.bin", 20000);
	/* A shrink, then data written past where the old data ended: the gap
	 * must read as zeros, never as the stale chunks still on the flash. */
	yaffs_truncate(M "/docs/gap.bin", 7000);
	pw(M "/docs/gap.bin", 60000, 2500, "after-gap");
	/* A file written only far from its start: a leading hole. */
	pw(M "/docs/hole.bin", 100000, 2500, "hole");
	/* A deleted file, a rename, a symlink, a hard link whose first name goes. */
	yaffs_unlink(M "/gone/deleted.txt");
	yaffs_rename(M "/old_name.txt", M "/docs/new_name.txt");
	yaffs_symlink("docs/big.bin", M "/link_to_big");
	yaffs_link(M "/docs/sub/linked.txt", M "/hardlink.txt");
	yaffs_unlink(M "/docs/sub/linked.txt");
	/* Churn: write and delete more than the device holds, so garbage
	 * collection copies live chunks into newer blocks. */
	for (round = 0; round < 12; round++) {
		snprintf(name, sizeof name, M "/churn_%02d.bin", round);
		put(name, churn, "churn");
		yaffs_unlink(name);
		snprintf(name, sizeof name, M "/docs/small_%02d.txt", round * 3);
		pw(name, 50, 60, "rewritten");
	}
	/* Last, a file whose data is flushed but whose header is not rewritten:
	 * fdatasync writes the data chunks only (core/yaffs_guts.c
	 * yaffs_flush_file), and it is never closed, so its size is only in the
	 * chunks written after its header. */
	fd = yaffs_open(M "/docs/unclosed.bin", O_CREAT | O_RDWR, S_IREAD | S_IWRITE);
	buf = malloc(9000);
	text(buf, 9000, "unclosed", 0);
	if (fd < 0 || yaffs_write(fd, buf, 9000) != 9000 || yaffs_fdatasync(fd) < 0) {
		fprintf(stderr, "unclosed write failed\n");
		return 1;
	}
	if (!is_yaffs2) {
		/* YAFFS1 only: keep writing and deleting until garbage collection
		 * copies a live data chunk, and lose power before the original is
		 * marked deleted. */
		cut_armed = 1;
		for (round = 0; round < 200; round++) {
			snprintf(name, sizeof name, M "/cut_%03d.bin", round);
			put(name, churn, "churn");
			yaffs_unlink(name);
		}
		fprintf(stderr, "the power cut never came\n");
		return 1;
	}
	/* No close, no sync, no unmount: nothing more is written. */
	return 0;
}

/* The "yaffs1cut" device: more chunks than a 16-bit tnode addresses, with wide
 * tnodes off, so each tnode names a group of chunks and YAFFS reads the old
 * tags when it rewrites one (core/yaffs_guts.c yaffs_find_chunk_in_group), and
 * so gives the new copy serial + 1. One chunk of one file is rewritten and the
 * flash stops before the old copy is marked deleted: two live copies with
 * different bytes, which only their serial numbers order. */
static int do_write_cut(void)
{
	if (yaffs_mount(M) < 0) {
		fprintf(stderr, "mount failed\n");
		return 1;
	}
	put(M "/before.txt", 3000, "before");
	put(M "/rewritten.txt", 3000, "original");
	cut_armed = 1;
	cut_on_mark = 1;
	pw(M "/rewritten.txt", 1024, 100, "rewrite");
	fprintf(stderr, "the power cut never came\n");
	return 1;
}

static FILE *listing;

static void walk(const char *dir, const char *rel, const char *out)
{
	yaffs_DIR *d = yaffs_opendir(dir);
	struct yaffs_dirent *de;
	if (!d)
		return;
	while ((de = yaffs_readdir(d)) != NULL) {
		char path[1024], r[1024], hostpath[1200];
		struct yaffs_stat st;
		snprintf(path, sizeof path, "%s/%s", dir, de->d_name);
		snprintf(r, sizeof r, "%s%s%s", rel, *rel ? "/" : "", de->d_name);
		if (yaffs_lstat(path, &st) < 0)
			continue;
		fprintf(listing, "%o %lld %llu %s\n", (unsigned)st.st_mode,
			(long long)st.st_size, (unsigned long long)st.yst_mtime, r);
		snprintf(hostpath, sizeof hostpath, "%s/files/%s", out, r);
		if ((st.st_mode & S_IFMT) == S_IFDIR) {
			mkdir(hostpath, 0755);
			walk(path, r, out);
		} else if ((st.st_mode & S_IFMT) == S_IFREG) {
			FILE *f = fopen(hostpath, "wb");
			int fd = yaffs_open(path, O_RDONLY, 0);
			char b[4096];
			int n;
			while ((n = yaffs_read(fd, b, sizeof b)) > 0)
				fwrite(b, 1, n, f);
			yaffs_close(fd);
			fclose(f);
		}
	}
	yaffs_closedir(d);
}

static int do_dump(const char *out)
{
	char p[1100];
	if (yaffs_mount3(M, 1, 1) < 0) {
		fprintf(stderr, "read-only mount failed\n");
		return 1;
	}
	snprintf(p, sizeof p, "%s/files", out);
	mkdir(out, 0755);
	mkdir(p, 0755);
	snprintf(p, sizeof p, "%s/listing", out);
	listing = fopen(p, "w");
	walk(M, "", out);
	fclose(listing);
	return 0;
}

int main(int argc, char **argv)
{
	int write_mode;
	if (argc < 4 || (strcmp(argv[1], "yaffs2") && strcmp(argv[1], "yaffs1")
			 && strcmp(argv[1], "yaffs1cut"))) {
		fprintf(stderr, "usage: yaffs_history yaffs2|yaffs1|yaffs1cut write IMAGE | "
			"dump IMAGE OUT\n");
		return 2;
	}
	is_yaffs2 = !strcmp(argv[1], "yaffs2");
	grouped = !strcmp(argv[1], "yaffs1cut");
	page_data = is_yaffs2 ? 2048 : 512;
	page_spare = is_yaffs2 ? 64 : 16;
	pages_per_block = is_yaffs2 ? 64 : 32;
	/* 4 MiB and 2 MiB of data; the cut device 67,584 chunks, past 65,536 */
	n_blocks = is_yaffs2 ? 32 : grouped ? 2112 : 128;
	write_mode = !strcmp(argv[2], "write");
	if (write_mode) {
		long total = (long)n_blocks * pages_per_block * (page_data + page_spare);
		static u8 ff[65536];
		long done;
		memset(ff, 0xff, sizeof ff);
		nand_fd = open(argv[3], O_RDWR | O_CREAT | O_TRUNC, 0644);
		for (done = 0; done < total; done += sizeof ff)
			if (write(nand_fd, ff, total - done < (long)sizeof ff ? total - done
								: (long)sizeof ff) < 0)
				return 1;
	} else {
		nand_fd = open(argv[3], O_RDONLY);
	}
	if (nand_fd < 0) {
		perror(argv[3]);
		return 1;
	}
	yaffs_start_up();
	if (write_mode)
		return grouped ? do_write_cut() : do_write();
	if (argc >= 5 && !strcmp(argv[2], "dump"))
		return do_dump(argv[4]);
	return 2;
}
