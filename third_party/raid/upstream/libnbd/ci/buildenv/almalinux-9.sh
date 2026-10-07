# THIS FILE WAS AUTO-GENERATED
#
#  $ lcitool manifest ci/manifest.yml
#
# https://gitlab.com/libvirt/libvirt-ci

function install_buildenv() {
    dnf --quiet update -y
    dnf --quiet install 'dnf-command(config-manager)' -y
    dnf --quiet config-manager --set-enabled -y crb
    dnf --quiet install -y epel-release
    dnf --quiet install almalinux-release-devel -y
    dnf --quiet config-manager --set-enabled -y devel
    dnf --quiet install -y \
                autoconf \
                automake \
                bash \
                bash-completion \
                ca-certificates \
                cargo \
                ccache \
                clang \
                diffutils \
                fuse3 \
                fuse3-devel \
                gawk \
                gcc \
                gcc-c++ \
                git \
                glib2-devel \
                glibc-devel \
                glibc-langpack-en \
                gnutls-devel \
                gnutls-utils \
                golang \
                iproute \
                jq \
                libev-devel \
                libtool \
                libxml2-devel \
                make \
                nbdkit \
                ocaml \
                ocaml-findlib \
                ocaml-ocamldoc \
                perl-Pod-Simple \
                perl-base \
                perl-podlators \
                pkgconfig \
                python3-devel \
                python3-flake8 \
                qemu-img \
                qemu-kvm \
                sed \
                tar \
                util-linux \
                valgrind
    rpm -qa | sort > /packages.txt
    mkdir -p /usr/libexec/ccache-wrappers
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/c++
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/cc
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/clang
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/g++
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/gcc
}

export CCACHE_WRAPPERSDIR="/usr/libexec/ccache-wrappers"
export LANG="en_US.UTF-8"
export MAKE="/usr/bin/make"
