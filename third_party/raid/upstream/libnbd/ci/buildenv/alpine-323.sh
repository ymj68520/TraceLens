# THIS FILE WAS AUTO-GENERATED
#
#  $ lcitool manifest ci/manifest.yml
#
# https://gitlab.com/libvirt/libvirt-ci

function install_buildenv() {
    apk update
    apk upgrade
    apk add \
        autoconf \
        automake \
        bash \
        bash-completion \
        busybox \
        ca-certificates \
        cargo \
        ccache \
        clang \
        diffutils \
        fuse3 \
        fuse3-dev \
        g++ \
        gcc \
        git \
        glib-dev \
        gnutls-dev \
        gnutls-utils \
        go \
        hexdump \
        iproute2 \
        jq \
        libev-dev \
        libtool \
        libxml2-dev \
        make \
        musl-dev \
        nbd \
        nbd-client \
        ocaml \
        ocaml-findlib-dev \
        ocaml-ocamldoc \
        perl \
        pkgconf \
        py3-flake8 \
        python3-dev \
        qemu \
        qemu-img \
        sed \
        tar \
        valgrind
    apk list --installed | sort > /packages.txt
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
