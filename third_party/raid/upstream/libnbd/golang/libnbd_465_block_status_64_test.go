/* libnbd golang tests
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

package libnbd

import (
	"fmt"
	"os"
	"strings"
	"testing"
)

var entries64 []LibnbdExtent

func mcf64(metacontext string, offset uint64, e []LibnbdExtent, error *int) int {
	if *error != 0 {
		panic("expected *error == 0")
	}
	if metacontext == "base:allocation" {
		entries64 = e
	}
	return 0
}

// Seriously WTF?
func mc64_compare(a1 []LibnbdExtent, a2 []LibnbdExtent) bool {
	if len(a1) != len(a2) {
		return false
	}
	for i := 0; i < len(a1); i++ {
		if a1[i] != a2[i] {
			return false
		}
	}
	return true
}

func mc64_to_string(a []LibnbdExtent) string {
	ss := make([]string, len(a))
	for i := 0; i < len(a); i++ {
		ss[i] = fmt.Sprintf("%#v", a[i])
	}
	return strings.Join(ss, ", ")
}

func Test465BlockStatus64(t *testing.T) {
	srcdir := os.Getenv("abs_top_srcdir")
	script := srcdir + "/tests/meta-base-allocation.sh"

	h, err := Create()
	if err != nil {
		t.Fatalf("could not create handle: %s", err)
	}
	defer h.Close()

	err = h.AddMetaContext("base:allocation")
	if err != nil {
		t.Fatalf("%s", err)
	}
	err = h.ConnectCommand([]string{
		"nbdkit", "-s", "--exit-with-parent", "-v",
		"sh", script,
	})
	if err != nil {
		t.Fatalf("%s", err)
	}

	err = h.BlockStatus64(65536, 0, mcf64, nil)
	if err != nil {
		t.Fatalf("%s", err)
	}
	if !mc64_compare(entries64, []LibnbdExtent{
		{8192, 0},
		{8192, 1},
		{16384, 3},
		{16384, 2},
		{16384, 0},
	}) {
		t.Fatalf("unexpected entries (1): %s", mc64_to_string(entries64))
	}

	err = h.BlockStatus64(1024, 32256, mcf64, nil)
	if err != nil {
		t.Fatalf("%s", err)
	}
	if !mc64_compare(entries64, []LibnbdExtent{
		{512, 3},
		{16384, 2},
	}) {
		t.Fatalf("unexpected entries (2): %s", mc64_to_string(entries64))
	}

	var optargs BlockStatus64Optargs
	optargs.FlagsSet = true
	optargs.Flags = CMD_FLAG_REQ_ONE
	err = h.BlockStatus64(1024, 32256, mcf64, &optargs)
	if err != nil {
		t.Fatalf("%s", err)
	}
	if !mc64_compare(entries64, []LibnbdExtent{{512, 3}}) {
		t.Fatalf("unexpected entries (3): %s", mc64_to_string(entries64))
	}

}
