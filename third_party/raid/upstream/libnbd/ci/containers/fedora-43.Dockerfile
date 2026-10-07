# THIS FILE WAS AUTO-GENERATED
#
#  $ lcitool manifest ci/manifest.yml
#
# https://gitlab.com/libvirt/libvirt-ci

FROM registry.fedoraproject.org/fedora:43

RUN dnf --quiet install -y nosync && \
    printf '#!/bin/sh\n\
if test -d /usr/lib64\n\
then\n\
    export LD_PRELOAD=/usr/lib64/nosync/nosync.so\n\
else\n\
    export LD_PRELOAD=/usr/lib/nosync/nosync.so\n\
fi\n\
exec "$@"\n' > /usr/bin/nosync && \
    chmod +x /usr/bin/nosync && \
    nosync dnf --quiet update -y && \
    nosync dnf --quiet install -y \
                       autoconf \
                       automake \
                       bash \
                       bash-completion-devel \
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
                       glibc-utils \
                       gnutls-devel \
                       gnutls-utils \
                       golang \
                       iproute \
                       jq \
                       libev-devel \
                       libtool \
                       libxml2-devel \
                       make \
                       nbd \
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
                       valgrind && \
    nosync dnf --quiet autoremove -y && \
    nosync dnf --quiet clean all -y && \
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
