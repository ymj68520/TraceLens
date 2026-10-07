# THIS FILE WAS AUTO-GENERATED
#
#  $ lcitool manifest ci/manifest.yml
#
# https://gitlab.com/libvirt/libvirt-ci

FROM registry.opensuse.org/opensuse/leap:15.6

RUN zypper update -y && \
    zypper addrepo -fc https://download.opensuse.org/update/leap/15.6/backports/openSUSE:Backports:SLE-15-SP6:Update.repo && \
    zypper install -y \
           autoconf \
           automake \
           awk \
           bash \
           bash-completion-devel \
           ca-certificates \
           cargo \
           ccache \
           clang \
           diffutils \
           fuse3 \
           fuse3-devel \
           gcc \
           gcc-c++ \
           git \
           glib2-devel \
           glibc-devel \
           glibc-locale \
           gnutls \
           go \
           iproute2 \
           jq \
           libev-devel \
           libgnutls-devel \
           libtool \
           libxml2-devel \
           make \
           nbd \
           nbdkit \
           ocaml \
           ocaml-findlib \
           ocaml-ocamldoc \
           perl \
           perl-base \
           pkgconfig \
           python3-devel \
           python3-flake8 \
           qemu \
           qemu-tools \
           sed \
           tar \
           util-linux \
           valgrind && \
    zypper clean --all && \
    rpm -qa | sort > /packages.txt && \
    mkdir -p /usr/libexec/ccache-wrappers && \
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/c++ && \
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/cc && \
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/clang && \
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/g++ && \
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/gcc

ENV CCACHE_WRAPPERSDIR="/usr/libexec/ccache-wrappers"
ENV LANG="en_US.UTF-8"
ENV MAKE="/usr/bin/make"
